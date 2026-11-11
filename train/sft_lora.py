"""LoRA SFT of the DataMate agent model (Gemma 4 12B-it) on a gen.package folder; loss on the final reply only.

Each sample is {"id", "prompt": [messages], "completion": [{"role": "assistant", "content": ...}]}. The prompt is
rendered with the model's own chat template exactly as vLLM renders it at inference (generation prompt, thinking off:
Gemma 4 then opens the reply with an empty thought channel), the target is the reply text plus the end-of-turn
token. Loss covers the target tokens only: never the prompt, never the earlier assistant turns inside the prompt
(they can be failed attempts the agent recovered from). Samples longer than --max-len are dropped, never truncated
(a right-truncated sample would lose its target). Tokenization is done here, not by TRL: TRL's conversational
prompt-completion path renders prompt+completion without the empty thought channel, so its prompt is not a prefix
and the target would be misaligned with what the model sees at inference.

Needs: torch, transformers >= 5 (Gemma 4), peft, accelerate (bitsandbytes for --qlora). NOT RUN in the dev
environment (no torch there); `--dry-run` needs only transformers (tokenizer) and checks the data.

  python sft_lora.py --data . --model google/gemma-4-12B-it --dry-run                    # lengths, masks, one sample
  python sft_lora.py --data . --model google/gemma-4-12B-it --out ckpt/smoke --max-steps 5   # smoke test first
  python sft_lora.py --data . --model google/gemma-4-12B-it --out ckpt/lora_v1            # 1 GPU (80 GB: bf16 LoRA)
  accelerate launch --num_processes 2 sft_lora.py --data . --model ... --out ckpt/lora_v1 # data parallel
  python sft_lora.py --model google/gemma-4-12B-it --merge ckpt/lora_v1 --out ckpt/merged_v1   # for vLLM
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
from pathlib import Path

LINEAR = ('q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj')
TOWERS = re.compile(r'vision|audio|multi_modal|mm_|embed_vision|embed_audio|image|projector', re.I)


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def end_of_turn(tok):
    """The text the chat template writes right after an assistant reply (Gemma 4: <turn|>, Gemma 3: <end_of_turn>):
    the token the model must learn to emit, the one vLLM stops on."""
    text = tok.apply_chat_template([{'role': 'user', 'content': 'x'}, {'role': 'assistant', 'content': 'REPLY'}], tokenize=False)
    tail = text.split('REPLY', 1)[1]
    eot = tail.strip().split('\n')[0].strip() if tail.strip() else ''
    if not eot or tok.convert_tokens_to_ids(eot) in (None, tok.unk_token_id):
        eot = tok.eos_token
    return eot


def encode(tok, sample, eot, max_len):
    """(input_ids, labels) of one sample, or None when longer than max_len. Labels are -100 on the prompt."""
    prompt_text = tok.apply_chat_template(sample['prompt'], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    target = sample['completion'][0]['content'].strip() + eot
    p = tok(prompt_text, add_special_tokens=False)['input_ids']
    c = tok(target, add_special_tokens=False)['input_ids']
    if len(p) + len(c) > max_len:
        return None
    return {'input_ids': p + c, 'labels': [-100] * len(p) + c}


def load_split(tok, path, eot, max_len, name):
    rows, dropped, lengths = [], 0, []
    for s in read_jsonl(path):
        enc = encode(tok, s, eot, max_len)
        if enc is None:
            dropped += 1
            continue
        rows.append(enc)
        lengths.append(len(enc['input_ids']))
    lengths.sort()
    if lengths:
        print(f"{name}: {len(rows)} samples, {dropped} dropped (> {max_len} tokens); tokens p50 {lengths[len(lengths) // 2]} "
              f"p99 {lengths[min(len(lengths) - 1, int(.99 * len(lengths)))]} max {lengths[-1]}; target tokens "
              f"{sum(sum(1 for x in r['labels'] if x != -100) for r in rows)}", flush=True)
    return rows, dropped


def dry_run(tok, a, eot):
    print(f'tokenizer {type(tok).__name__}: bos {tok.bos_token!r} eos {tok.eos_token!r} pad {tok.pad_token!r} end of turn {eot!r}')
    train, _ = load_split(tok, a.train, eot, a.max_len, 'train')
    if a.val:
        load_split(tok, a.val, eot, a.max_len, 'val')
    if not train:
        raise SystemExit('no training sample fits --max-len')
    r = train[0]
    first = next(i for i, x in enumerate(r['labels']) if x != -100)
    if r['input_ids'][0] != tok.bos_token_id:
        print('WARNING: the prompt does not start with bos')
    print('--- end of prompt | start of target ---')
    print(tok.decode(r['input_ids'][max(0, first - 30):first]) + ' |||| ' + tok.decode(r['input_ids'][first:first + 40]))
    print('--- end of target ---')
    print(tok.decode(r['input_ids'][-20:]))


def collate(pad_id, with_token_types):
    def fn(batch):
        n = max(len(b['input_ids']) for b in batch)
        import torch
        ids = torch.full((len(batch), n), pad_id, dtype=torch.long)
        labels = torch.full((len(batch), n), -100, dtype=torch.long)
        mask = torch.zeros((len(batch), n), dtype=torch.long)
        for i, b in enumerate(batch):                       # right padding
            k = len(b['input_ids'])
            ids[i, :k] = torch.tensor(b['input_ids'])
            labels[i, :k] = torch.tensor(b['labels'])
            mask[i, :k] = 1
        out = {'input_ids': ids, 'attention_mask': mask, 'labels': labels}
        if with_token_types:                                # Gemma multimodal models ask for it in training (text: 0)
            out['token_type_ids'] = torch.zeros_like(ids)
        return out
    return fn


def lora_targets(model):
    """Linear layers of the language model only (the vision/audio towers stay frozen and untouched)."""
    names = [n for n, m in model.named_modules() if n.rsplit('.', 1)[-1] in LINEAR and not TOWERS.search(n)
             and type(m).__name__.endswith('Linear')]
    if not names:
        raise SystemExit('no LoRA target found: check the model layer names')
    return names


def make_trainer_class():
    import torch
    import torch.nn.functional as F
    from transformers import Trainer

    class CompletionTrainer(Trainer):
        """Loss = mean cross-entropy over the target tokens of each micro-batch. Logits are computed only for the
        positions from the first target token on (logits_to_keep): a 20k-token prompt with a 262k vocabulary would
        otherwise need ~20 GB for the logits alone."""
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            self.model_accepts_loss_kwargs = False          # the Trainer divides by gradient accumulation steps

        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            labels = inputs.pop('labels')
            n = labels.shape[1]
            has = (labels != -100)
            first = int(torch.where(has.any(1), has.float().argmax(1), torch.full_like(has[:, 0], n, dtype=torch.long)).min())
            keep = n - first + 1                            # positions first-1 .. n-1 predict tokens first .. n-1
            try:
                out = model(**inputs, logits_to_keep=keep)
                logits = out.logits
                if logits.shape[1] != keep:
                    raise TypeError('logits_to_keep ignored')
            except TypeError:
                out = model(**inputs)
                logits = out.logits[:, n - keep:]
            loss = F.cross_entropy(logits[:, :-1].float().reshape(-1, logits.shape[-1]), labels[:, n - keep + 1:].reshape(-1),
                                   ignore_index=-100)
            return (loss, out) if return_outputs else loss

    return CompletionTrainer


def load_model(a, quant=None):
    import torch
    from transformers import AutoModelForCausalLM
    kw = dict(dtype=torch.bfloat16, attn_implementation=a.attn, quantization_config=quant)
    try:
        return AutoModelForCausalLM.from_pretrained(a.model, **kw)
    except (ValueError, KeyError):                          # multimodal checkpoints without a causal-LM mapping
        from transformers import AutoModelForImageTextToText
        return AutoModelForImageTextToText.from_pretrained(a.model, **kw)


def merge(a):
    """Base model in bf16 + adapter -> one merged folder vLLM serves (weights, tokenizer, chat template, processor)."""
    import torch  # noqa: F401
    from peft import PeftModel
    from transformers import AutoTokenizer
    model = PeftModel.from_pretrained(load_model(a), a.merge).merge_and_unload()
    model.save_pretrained(a.out, safe_serialization=True)
    AutoTokenizer.from_pretrained(a.model).save_pretrained(a.out)
    try:
        from transformers import AutoProcessor
        AutoProcessor.from_pretrained(a.model).save_pretrained(a.out)
    except Exception as exc:                                # noqa: BLE001 - text-only use does not need it
        print(f'processor not saved ({type(exc).__name__}: {exc}); copy processor_config.json from the base model if vLLM asks')
    print(f'merged model -> {a.out}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--data', help='package folder (train.jsonl, val.jsonl); or --train/--val')
    ap.add_argument('--train')
    ap.add_argument('--val')
    ap.add_argument('--model', required=True, help='base model (HF id or folder), e.g. google/gemma-4-12B-it')
    ap.add_argument('--out', help='output folder (adapter checkpoints; or the merged model with --merge)')
    ap.add_argument('--max-len', type=int, default=24576, help='drop longer samples (see the package README)')
    ap.add_argument('--epochs', type=float, default=2)
    ap.add_argument('--lr', type=float, default=1e-4)
    ap.add_argument('--rank', type=int, default=16)
    ap.add_argument('--alpha', type=int, help='LoRA alpha (default 2 x rank)')
    ap.add_argument('--dropout', type=float, default=0.05)
    ap.add_argument('--batch', type=int, default=1, help='per device; 1 avoids padding 20k-token sequences')
    ap.add_argument('--accum', type=int, default=16, help='gradient accumulation steps (effective batch = batch x accum x GPUs)')
    ap.add_argument('--warmup', type=float, default=0.03)
    ap.add_argument('--attn', default='sdpa', help='attention implementation (sdpa; flash_attention_2 does not support head_dim 512)')
    ap.add_argument('--qlora', action='store_true', help='4-bit base (bitsandbytes): ~40 GB GPU instead of ~80 GB')
    ap.add_argument('--max-steps', type=int, default=-1, help='stop after N optimizer steps (smoke test: 5)')
    ap.add_argument('--eval-steps', type=int, default=100)
    ap.add_argument('--save-steps', type=int, default=100)
    ap.add_argument('--resume', action='store_true', help='resume from the last checkpoint in --out')
    ap.add_argument('--merge', metavar='ADAPTER', help='merge this adapter into --model and save to --out, then exit')
    ap.add_argument('--dry-run', action='store_true', help='tokenizer only: lengths, masks, one sample (no torch needed)')
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    if a.data:
        a.train = a.train or os.path.join(a.data, 'train.jsonl')
        val = os.path.join(a.data, 'val.jsonl')
        a.val = a.val or (val if os.path.exists(val) and os.path.getsize(val) else None)
    if a.merge:
        if not a.out:
            raise SystemExit('--merge needs --out')
        return merge(a)
    if not a.train:
        raise SystemExit('pass --data <package> or --train <file>')

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.model)
    eot = end_of_turn(tok)
    if a.dry_run:
        return dry_run(tok, a, eot)
    if not a.out:
        raise SystemExit('pass --out')

    import inspect

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import BitsAndBytesConfig, TrainingArguments, set_seed

    set_seed(a.seed)
    random.seed(a.seed)
    train, _ = load_split(tok, a.train, eot, a.max_len, 'train')
    val, _ = load_split(tok, a.val, eot, a.max_len, 'val') if a.val else ([], 0)
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16) if a.qlora else None
    model = load_model(a, quant)
    model.config.use_cache = False
    if a.qlora:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                                gradient_checkpointing_kwargs={'use_reentrant': False})
    targets = lora_targets(model)
    print(f'LoRA on {len(targets)} linear layers, e.g. {targets[0]}')
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=a.alpha or 2 * a.rank, lora_dropout=a.dropout,
                                             target_modules=targets, task_type='CAUSAL_LM'))
    model.enable_input_require_grads()
    model.print_trainable_parameters()
    base = model.get_base_model()
    with_token_types = 'token_type_ids' in inspect.signature(base.forward).parameters

    class ListDataset(torch.utils.data.Dataset):
        def __init__(self, rows):
            self.rows = rows

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, i):
            return self.rows[i]

    world = int(os.environ.get('WORLD_SIZE', 1))
    steps = math.ceil(len(train) / (a.batch * a.accum * world)) * a.epochs
    args = TrainingArguments(output_dir=a.out, num_train_epochs=a.epochs, max_steps=a.max_steps, learning_rate=a.lr, lr_scheduler_type='cosine',
                             warmup_ratio=a.warmup, weight_decay=0.0, per_device_train_batch_size=a.batch,
                             per_device_eval_batch_size=1, gradient_accumulation_steps=a.accum, gradient_checkpointing=True,
                             gradient_checkpointing_kwargs={'use_reentrant': False}, bf16=True, logging_steps=5,
                             eval_strategy='steps' if val else 'no', eval_steps=a.eval_steps, save_strategy='steps',
                             save_steps=a.save_steps, save_total_limit=3, seed=a.seed, report_to=[],
                             remove_unused_columns=False, dataloader_num_workers=1, group_by_length=False,
                             prediction_loss_only=True, label_names=['labels'],
                             ddp_find_unused_parameters=False)
    print(f'about {int(steps)} optimizer steps; effective batch {a.batch * a.accum * world}')
    trainer = make_trainer_class()(model=model, args=args, train_dataset=ListDataset(train),
                                   eval_dataset=ListDataset(val) if val else None,
                                   data_collator=collate(tok.pad_token_id, with_token_types))
    trainer.train(resume_from_checkpoint=True if a.resume else None)
    trainer.save_model(a.out)
    tok.save_pretrained(a.out)
    with open(os.path.join(a.out, 'sft_args.json'), 'w', encoding='utf-8') as f:
        json.dump({**vars(a), 'end_of_turn': eot, 'lora_targets': len(targets), 'train_samples': len(train),
                   'val_samples': len(val)}, f, indent=1)
    print(f'adapter -> {a.out}; merge for vLLM: python {sys.argv[0]} --model {a.model} --merge {a.out} --out <merged dir>')


if __name__ == '__main__':
    main()
