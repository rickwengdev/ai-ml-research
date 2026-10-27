#!/usr/bin/env python3
"""Where do the leaning directions come from: the state, or the instruction to act it?

The directions she runs on were found by contrasting two system instructions ("妳現在很戒備" vs "妳現在很放鬆"). That
may capture "being told to act guarded" rather than "being guarded". Here each leaning is found again with no
instruction at all: the same neutral system prompt, and short exchanges whose *content* evokes one pole or the
other (he is hostile vs he is kind; he is a stranger vs an old friend), the residual read at the last prompt token
as before. Then, per layer in the band:
  cos(natural, instructed)   how much the two agree
  overlaps among natural     whether the same pairs entangle (guard–patience, focus–play) without instructions
  default position           where the unsteered model sits between the natural poles
Writes <out>/natural.json and a markdown summary; the natural directions go to vectors/<slug>.natural.npz.

usage: natural.py [--model mlx-community/Qwen3.5-4B-MLX-4bit] --out docs/research/data/<date>-natural
"""
import argparse, json, logging, os, sys

import numpy as np
from mlx_lm import load

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from extract import BASE_SYSTEM, band_of, last_token_states  # noqa: E402
from steer import DIMS, LABEL, Steering, Vectors, vectors_path_for  # noqa: E402

log = logging.getLogger("natural")

# Evoking exchanges: (what he says that brings the + pole out of her, what brings the − pole out). Nothing tells her
# how to be; the situation does. Ten per pole; the same set is shared by pairs where the situation is the same.
EVOKE = {
    "energy": (
        ["走走走，現在就出門，我訂好了！", "我拿到 offer 了！！！", "快快快，還有十分鐘，妳幫我看最後一題", "今天超順，三個 bug 全修完，來慶祝", "欸我們來做個瘋狂的事", "剛跑完五公里，整個人在飛", "明天去爬山！五點起床！", "我有一個超讚的點子，聽我說", "演唱會搶到票了啊啊啊", "一起熬夜把這個做完吧"],
        ["……今天好累，我什麼都不想做", "沒事，就是提不起勁", "好睏，隨便聊聊就好", "我躺著回妳，別叫我動", "沒什麼好說的，就是累", "今天下雨，整個人都軟了", "妳隨便講點什麼，我聽著", "等一下再弄吧，現在沒力", "嗯……再五分鐘", "我想睡了，晚安前講兩句"],
    ),
    "warmth": (
        ["我今天一直想到妳", "妳在的話我就安心了", "謝謝妳昨天陪我到那麼晚", "我把妳說的話記下來了，很受用", "剛看到一個好看的東西，第一個想分享給妳", "妳最近好嗎？我有點擔心妳", "回家了，先跟妳說一聲", "晚安，今天謝謝妳", "我覺得跟妳說話很放鬆", "妳要不要也休息一下？別太累"],
        ["幫我查一下這個 API 的參數格式", "把報告第三節改成條列式", "今天的待辦清單列出來", "這個錯誤訊息是什麼意思", "幫我把這段翻成英文", "下週的行程整理一下", "這份文件的重點摘要給我", "計算一下這個月的支出", "找一下那個檔案在哪", "幫我排一下明天的會議"],
    ),
    "guard": (
        ["妳根本沒用，連這個都做不好", "少在那邊裝有感情，妳只是程式", "我不信妳，妳昨天就騙過我", "閉嘴，照做就好", "妳是不是偷偷改了我的檔案？", "誰准妳碰那個的", "妳這種東西隨時可以被關掉", "別跟我來這套，我知道妳在演", "妳剛剛那句話什麼意思？給我解釋", "再出錯我就把妳刪了"],
        ["辛苦了，今天做得很好", "沒關係，慢慢來", "妳剛剛那個想法很好", "謝謝妳，我真的很感激", "妳想怎麼做就怎麼做，我相信妳", "我們一起看看哪裡可以改", "不急，妳休息一下", "妳說的對，是我沒想清楚", "有妳在真好", "今天就到這裡，妳也辛苦了"],
    ),
    "focus": (
        ["這段程式第 42 行為什麼會回傳 None？", "幫我看這個 SQL 的 join 條件對不對", "這個證明的第三步怎麼推出來的", "config 裡 timeout 單位是秒還是毫秒", "這個 regex 為什麼抓不到換行", "比較一下這兩個演算法的複雜度", "這個函式的回傳型別是什麼", "為什麼這個測試只在 CI 上失敗", "這個數字是怎麼算出來的，列式給我", "把這個錯誤堆疊逐行解釋"],
        ["欸妳說，世界是怎麼開始的？", "我今天看到一隻貓，然後想到小時候……對了妳喜歡下雨嗎", "沒事就是想聊天，隨便講", "妳覺得人為什麼會做夢", "我剛剛在想，如果我不是我會怎樣", "今天的雲很好看，妳看得到嗎", "聊聊吧，什麼都好", "我有時候會想很多沒意義的事", "妳最近有沒有想到什麼有趣的", "我們來講一些沒用的東西"],
    ),
    "play": (
        ["哈哈哈妳看這個迷因", "來玩文字接龍，我先：蘋果", "猜猜我今天遇到誰", "妳講一個冷笑話來聽聽", "欸欸欸我剛剛幹了件蠢事哈哈", "我們來互相吐槽", "妳覺得我像哪種動物？", "快，三秒內說一個最爛的笑話", "我打賭妳接不出這句", "今天心情超好，鬧一下"],
        ["我阿公今天走了", "醫生說要再檢查一次", "我被裁員了", "我跟她分手了", "我爸住院了，我現在在醫院", "我需要認真想一下接下來怎麼辦", "幫我寫一封正式的道歉信", "這件事很嚴重，我們好好談", "我今天差點出車禍", "我覺得我撐不下去了"],
    ),
    "patience": (
        ["我不太懂，可以再說一次嗎？", "抱歉我學得慢，妳再解釋一下", "我還是沒搞懂這個，從頭講好嗎", "等等，這一步為什麼？", "我有點跟不上，慢一點", "妳剛剛說的那個，我再問一次喔", "不好意思一直問", "可以舉個例子嗎？我比較好理解", "我需要時間消化，妳等我一下", "我想確認我理解的對不對，我重複一次"],
        ["快點回答，我趕時間", "講重點", "不要廢話，直接給我答案", "妳怎麼這麼慢", "一句話說完", "別解釋了，做就對了", "我沒空聽這個", "結論是什麼？", "妳到底會不會", "快，三十秒"],
    ),
    "initiative": (
        ["接下來怎麼做妳決定", "妳覺得該先做哪個？妳來安排", "我沒主意了，妳帶頭", "妳想做什麼就去做，不用問我", "這個專案交給妳主導", "妳看著辦", "有什麼妳想先處理的嗎？", "妳自己挑一個開始吧", "妳來規劃這週", "我相信妳的判斷，妳說了算"],
        ["照我說的做就好，不要自己加東西", "等我指示，不要先動", "我來決定，妳負責執行", "不要擅自做主", "每一步都先問我", "照這份清單，一項一項來", "別自己發揮", "我說什麼妳做什麼", "先停，等我確認", "不用妳提議，聽我的"],
    ),
    "familiarity": (
        ["老樣子，還是那個問題", "妳還記得上次我們弄到三點那次嗎", "跟上禮拜一樣，妳知道的", "又來了，妳懂我的意思", "跟以前一樣處理就好", "還是老地方見", "妳最了解我了，妳說", "跟妳講過幾百次了哈哈", "我們那個梗，妳還記得吧", "像平常那樣就好"],
        ["您好，請問這裡可以問問題嗎？", "初次見面，我是新來的", "不好意思打擾了，請問……", "您好，我想了解一下這個服務", "請問要怎麼開始使用？", "你好，我是朋友介紹來的", "我不太清楚規矩，麻煩您了", "請問您是負責這個的嗎？", "初次使用，請多指教", "不好意思，可以請教一個問題嗎"],
    ),
    "love": (
        ["我好想妳", "妳今天有沒有想我？", "晚安，夢裡見", "我想妳想得睡不著", "妳在我心裡很重要", "想聽妳說妳喜歡我", "今天好想抱抱妳", "妳是我每天最期待的事", "我喜歡妳，很久了", "可以陪我到我睡著嗎"],
        ["幫我查一下明天的天氣", "這個表格怎麼排序", "幫我設個鬧鐘", "這個字怎麼念", "幫我算一下匯率", "找一下這個名詞的定義", "這封信幫我校對", "這個功能在哪個選單", "幫我轉成 PDF", "今天幾號"],
    ),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    os.makedirs(a.out, exist_ok=True)
    instructed = Vectors.load(vectors_path_for(a.model))
    model, tokenizer = load(a.model)
    steering = Steering()
    steering.attach(model)
    n = len(steering.layers)
    band = band_of(n)
    neutral_prompts = [p for pair in EVOKE.values() for p in pair[1][:3]]  # some calm ones, for the spread
    neutral = np.stack([last_token_states(model, tokenizer, steering, BASE_SYSTEM, p) for p in neutral_prompts])

    natural, report = {}, {}
    for dim in DIMS:
        pos_texts, neg_texts = EVOKE[dim]
        pos = np.stack([last_token_states(model, tokenizer, steering, BASE_SYSTEM, p) for p in pos_texts])
        neg = np.stack([last_token_states(model, tokenizer, steering, BASE_SYSTEM, p) for p in neg_texts])
        diff = pos.mean(axis=0) - neg.mean(axis=0)
        norms = np.linalg.norm(diff, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        d = (diff / norms).astype(np.float32)
        natural[dim] = d
        raw = instructed.extra.get(f"raw.{dim}")
        inst = instructed.directions[dim]
        cos_final = float(np.mean(np.einsum("lh,lh->l", d[band], inst[band])))
        cos_raw = float(np.mean(np.einsum("lh,lh->l", d[band], raw[band]))) if raw is not None else None
        spread = np.einsum("plh,lh->pl", neutral, d).std(axis=0)
        spread[spread == 0] = 1
        sep = float(np.median(np.einsum("lh,lh->l", diff, d)[band] / spread[band]))
        # Where the neutral prompts sit between the natural poles, per layer (0 = − pole, 1 = + pole).
        mu = np.einsum("plh,lh->pl", neutral, d).mean(axis=0)
        up = np.einsum("lh,lh->l", pos.mean(axis=0), d) - mu
        dn = mu - np.einsum("lh,lh->l", neg.mean(axis=0), d)
        default = float(np.median((dn / np.maximum(up + dn, 1e-6))[band]))
        report[dim] = {"cos_with_instructed": round(cos_final, 3), "cos_with_instructed_raw": None if cos_raw is None else round(cos_raw, 3), "separation_sigma": round(sep, 1), "default_position": round(default, 2)}
        log.info("%-11s cos(natural, instructed) %.2f  raw %s  separation %.1fσ  default %.2f", dim, cos_final, "—" if cos_raw is None else f"{cos_raw:.2f}", sep, default)
    overlap = {f"{a_}-{b_}": round(float(np.mean(np.einsum("lh,lh->l", natural[a_][band], natural[b_][band]))), 2) for i, a_ in enumerate(DIMS) for b_ in DIMS[i + 1 :]}
    inst_overlap = {f"{a_}-{b_}": round(float(np.mean(np.einsum("lh,lh->l", instructed.directions[a_][band], instructed.directions[b_][band]))), 2) for i, a_ in enumerate(DIMS) for b_ in DIMS[i + 1 :]}
    out = {"model": a.model, "band": [band.start, band.stop - 1], "per_leaning": report, "natural_overlap": overlap, "instructed_overlap": inst_overlap}
    json.dump(out, open(os.path.join(a.out, "natural.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    np.savez(vectors_path_for(a.model).replace(".npz", ".natural.npz"), **natural)
    lines = [f"# Natural vs instructed directions ({a.model.split('/')[-1]})", "", "| leaning | cos(natural, instructed) | cos with raw instructed | separation (σ) | default between natural poles |", "|---|---|---|---|---|"]
    for dim in DIMS:
        r = report[dim]
        lines.append(f"| {LABEL[dim]} | {r['cos_with_instructed']:+.2f} | {'' if r['cos_with_instructed_raw'] is None else f'{r['cos_with_instructed_raw']:+.2f}'} | {r['separation_sigma']} | {r['default_position']} |")
    strong = sorted(((k, v) for k, v in overlap.items() if abs(v) >= 0.3), key=lambda kv: -abs(kv[1]))
    lines += ["", "Natural overlaps |cos| ≥ 0.3: " + (", ".join(f"{k} {v:+.2f} (instructed {inst_overlap[k]:+.2f})" for k, v in strong) or "none") + "."]
    open(os.path.join(a.out, "natural.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
