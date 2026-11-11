"""LoRA SFT of the agent model on gen.mix chat lines (loss on the assistant JSON only).

NOT RUN in the dev environment (no torch there). Needs: torch, transformers, peft, trl, datasets (bitsandbytes for
--qlora). Example (2 GPUs):
  accelerate launch train/sft_lora.py --model google/gemma-4-12b-it --train train.jsonl --eval eval.jsonl \
      --out ckpt/lora_v1 --max-len 16384 --epochs 2 --lr 1e-4 --rank 32
The merged model (--merge) is what vLLM serves at inference (Rule 2: ≤ 15B params, weights in the image).
"""
from __future__ import annotations

import argparse
import json


def load_rows(path):
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True)
    ap.add_argument('--train', required=True)
    ap.add_argument('--eval')
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-len', type=int, default=16384)
    ap.add_argument('--epochs', type=float, default=2)
    ap.add_argument('--lr', type=float, default=1e-4)
    ap.add_argument('--rank', type=int, default=32)
    ap.add_argument('--batch', type=int, default=1)
    ap.add_argument('--accum', type=int, default=16)
    ap.add_argument('--qlora', action='store_true')
    ap.add_argument('--merge', action='store_true')
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    tok = AutoTokenizer.from_pretrained(a.model)
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                               bnb_4bit_compute_dtype=torch.bfloat16) if a.qlora else None
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.bfloat16, quantization_config=quant,
                                                 attn_implementation='sdpa')
    model.config.use_cache = False

    def ds(path):
        rows = [{'messages': r['messages']} for r in load_rows(path)]
        return Dataset.from_list(rows)

    cfg = SFTConfig(output_dir=a.out, num_train_epochs=a.epochs, learning_rate=a.lr, lr_scheduler_type='cosine',
                    warmup_ratio=0.03, per_device_train_batch_size=a.batch, gradient_accumulation_steps=a.accum,
                    gradient_checkpointing=True, bf16=True, logging_steps=10, save_strategy='epoch',
                    eval_strategy='epoch' if a.eval else 'no', max_length=a.max_len,
                    assistant_only_loss=True, packing=False, seed=a.seed, report_to=[])
    lora = LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, task_type='CAUSAL_LM',
                      target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj'])
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds(a.train), eval_dataset=ds(a.eval) if a.eval else None,
                         processing_class=tok, peft_config=lora)
    trainer.train()
    trainer.save_model(a.out)
    if a.merge:
        merged = trainer.model.merge_and_unload()
        merged.save_pretrained(a.out + '_merged', safe_serialization=True)
        tok.save_pretrained(a.out + '_merged')


if __name__ == '__main__':
    main()
