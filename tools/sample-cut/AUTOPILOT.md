# Autopilot: raw footage in, finished video out (runbook for Codex)

Trigger: the user points at a footage folder and asks for a video ("用 ~/Movies/素材/一茶 做视频", "make a video from …", "全自动做一条").

**Do not ask the user anything between the trigger and the delivery.** Make every judgement call yourself, write down why in `notes.md`, and report at the end. The only things that stay with the user are one-time setup (their own key, their own voice) and pressing Publish on Douyin.

All commands below are `sc <script> …` = `uv run --project <repo>/tools/sample-cut python <repo>/tools/sample-cut/<script> …`, run inside the project work dir.

## 0. Once per machine

```bash
sc autopilot_setup.py            # fonts, BGM library, default settings, readiness report
```

Exit code 1 means there is no voice route: no DashScope key in the environment and no local CosyVoice. In that case, tell the user exactly that, once, and stop. Otherwise continue.

## 1. Project folder

- macOS: `~/Movies/VideoWorkbench Projects/<商品>-<yyyymmdd>/work`
- Windows: `<repo>/data/projects/<商品>-<yyyymmdd>/work`

Create the folder, `cd` into it, and keep everything for this video inside it. Never write into the footage folder.

## 2. Index the footage

```bash
sc scan_materials.py "<footage folder>"
```

This writes `takes/clips.json` and the contact sheets `takes/sheets/sheet-NN.jpg`. Each column is one clip, labelled with its id (c001…), with 4 frames down the column and the time in yellow.

**Save tokens:** if the footage folders already have meaningful names (`folder` in clips.json, e.g. "13.倒水", "5.配料表"), trust them for the first pass. Then look only at the sheets you need to pick the best clips in each type. With no useful names, look at every sheet once.

## 3. Classify and select (judgement)

Shot types are the keys of `taxonomy.json`: 倒水 开盖 产品正面 产品细节 配料表 制作过程 成品展示 品尝 多件陈列 场景.

For each type, keep the best 1-3 clips. Write them to `takes/selected-takes.json`:

```json
{"倒水": [{"file": "<clips.json file>", "rank": 1, "in": 1.1, "out": 2.5, "subject_center": [0.5, 0.45], "suggest_zoom": 1.1, "why": "水柱连续、标签可读"}]}
```

- `in`/`out`: the 0.6–2 s where the action looks best, read from the sheet timestamps. Open a single full frame only when unsure: `ffmpeg -ss <t> -i <file> -frames:v 1 f.jpg`.
- Prefer: label readable, steady, clean background, good light, the product in frame.
- Reject: shaky clips, label hidden, laptop or phone screens, lyrics or other people's content, faces you don't need.
- `subject_center` is where the product or action is (0-1). Raise `suggest_zoom` (≤1.2) to crop distractions.
- The opening shot type should be 倒水, or the most dynamic action shot if there is no pour. Aim for 6-10 types in total.
- Write each rejection reason and each material problem into `notes.md` as one line, e.g. "背景笔记本屏幕在放歌词，已放大裁掉".

## 4. Read the package (facts)

```bash
sc ocr_text.py <ids of 配料表 / 产品正面 / 产品细节 clips>
```

OCR on curved bottles is noisy ("450mL" / "45L" / "45CmL"). For each fact you want to use, follow this rule:

1. It must appear consistently in the OCR output.
2. Confirm it once on a sharp full-resolution frame.
3. Only then write it to `facts_from_package`.

Never infer facts that aren't printed. That means no efficacy, no "健康", and no comparisons.

## 5. Write the copy (judgement)

Write `copy.json`, following the structure of `examples/copy.json`. The rules:

- Use `product`, `facts_from_package`, and `not_claimed` (list what you deliberately left out).
- 12 sentences or so, 140-155 characters in total, 7 characters/s, which is about 21 s.
- Structure: hook, product name, 2-4 facts, how it's enjoyed (shown in the shots), usage scenes, call to action ("喜欢的宝子，点左下角带一箱回家！"). The voice is an energetic Douyin seller, but plain and true.
- Each sentence's `shots` must be types that exist in `selected-takes.json`. Optional `emphasis` takes 1-2 words of that sentence to highlight.
- `style` is optional. Leave it out for the automatic pick, or choose one from `styles.json` that fits the product mood.
- `post_caption` is optional: one short line for the Douyin caption. Facts only, no hashtags spam.

Then:

```bash
sc make_spec.py "<封面标题，如 一茶茉莉白牡丹>"
sc copy_check.py      # exit 1 = fix copy.json and run again; never skip
```

## 6. Produce, QA, deliver (scripts)

```bash
sc produce.py
```

Copy check, then voice (whole script), timing, render, 3 BGM versions, QA, cover, phone previews, and the delivery folder.

- **Exit 0:** done.
- **Exit 2:** QA has hard fails. Read `renders/final/qa.json`, fix the cause, and run again with `--name final2`:
  - Voice accuracy below 90%: rewrite the hard-to-read words.
  - Too long or too short: adjust the copy length.
  - True peak or loudness: report it, don't hand-edit the audio.
- Do at most 2 retries, then deliver anyway and list the open problems in the report.
- Long steps (local voice can take minutes): wait for the command. Don't poll logs repeatedly.

## 7. Report to the user

Send the main video (and phone preview) and summarise in a few lines:

- Delivery folder
- Duration, shots, caption style, voice, BGM
- QA result
- Material problems from `notes.md`
- Reminder: paste `发布文案.txt` (including the BGM credit) into the Douyin caption, and publish it yourself.

## Hard rules

- Copy facts come only from the package (step 4). `copy_check.py` must pass.
- Voice is a cloud preset voice, or a clone of the user's **own** recorded voice (`autopilot_setup.py --own-voice`). Never clone a voice taken from other videos or a third-party model of a real or branded voice.
- BGM comes only from the CC BY library, with its credit in the caption. Never download Douyin or Jianying library music.
- Never publish, log in, or press anything on Douyin for the user.
- Never edit or delete the user's footage. Never modify existing Jianying drafts (the `--draft` option only adds a new one).
