# Autopilot: raw footage in, finished video out (runbook for Codex)

Trigger: the user points at a footage folder and asks for a video ("用 ~/Movies/素材/一茶 做视频", "make a video from …", "全自动做一条").

**Do not ask the user anything between the trigger and the delivery.** Make every judgement call yourself, write down why in `notes.md`, and report at the end. The only things that stay with the user are one-time setup (their own key, their own voice) and pressing Publish on Douyin.

All commands below are `sc <script> …` = `uv run --project <repo>/tools/sample-cut python <repo>/tools/sample-cut/<script> …`, run inside the project work dir.

## 0. Once per machine

```bash
sc autopilot_setup.py            # fonts, BGM library, default settings, readiness report
```

Exit code 1 means there is no voice route: no local CosyVoice (and no DashScope key either). In that case, tell the user exactly that, once, and stop. Otherwise continue.

### Preset voices (one-time, when the user hands over recordings)

The voice is local CosyVoice with a preset from the voice library. When the user gives you a recording for a preset:

```bash
sc voices.py add "<录音文件>" --name 女声活泼 --text "<录音里的每一个字>" --consent own [--tags 女声,活泼] [--preview]
sc voices.py add "<录音文件>" --name 同事小王 --text "…" --consent permission --who "王某，书面同意 2026-11-09"
sc voices.py list            # presets, which one is default, preview files
sc voices.py default <name>  # used when a video doesn't name a voice
```

- Ask once who is speaking, if the user hasn't said. Only the user's own voice (`own`) or a person who gave written permission (`permission`, with `--who`). Refuse recordings cut from other people's videos, livestreams or ads, and any "主播/明星音色" model, whatever the purpose.
- `--text` must match the recording word for word. If the user didn't give it, listen with them or ask them to type it. Don't guess.
- 5-15 s of clean speech, one speaker, no music. The tool trims silence and levels the volume.
- `--preview` makes `试听.wav` in the preset folder (a few minutes on CPU). Send it to the user to approve.

### 我的BGM (the user's own music)

`autopilot_setup.py` creates the folder and prints it as `my_bgm_dir`: `~/Movies/VideoWorkbench 我的BGM` (macOS) or `<repo>/data/我的BGM` (Windows). Tracks there are used before the built-in library. Bass-only tracks are skipped when better ones exist. A same-name `.txt` holds a credit line, which is copied into 发布文案.txt. `sc my_bgm.py` lists the tracks with their phone scores.

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
- `voice` is optional: the name of a preset from `voices.py list`. Leave it out to use the default voice. Use it only when the user asked for a specific voice for this product.

Then:

```bash
sc make_spec.py "<封面标题，如 一茶茉莉白牡丹>"
sc copy_check.py      # exit 1 = fix copy.json and run again; never skip
```

## 6. Produce, QA, deliver (scripts)

```bash
sc produce.py
```

Copy check, then voice (whole script, local CosyVoice with the preset), timing, render, up to 3 BGM versions (我的BGM first), QA, cover, phone previews, and the delivery folder with a 无BGM版 for picking music inside Douyin. `--voice-name <preset>` overrides the voice for this run.

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
- Reminder: paste `发布文案.txt` (including any BGM credit) into the Douyin caption, and publish it yourself. To use a trending track from Douyin's own library, upload `<商品>-无BGM版.mp4` and pick the music in Douyin.

## Hard rules

- Copy facts come only from the package (step 4). `copy_check.py` must pass.
- Voice is local CosyVoice with a preset of the user's **own** voice or a voice with written permission (`voices.py add --consent own|permission`). The cloud voice is only a fallback when CosyVoice isn't installed. Never clone a voice taken from other videos or a third-party model of a real or branded voice.
- BGM comes from the user's 我的BGM folder (the user is responsible for the rights to tracks they put there) or the built-in CC BY library, with its credit in the caption. Never download Douyin or Jianying library music, or music ripped from other videos. If you fetch tracks for the user, take them only from sources whose license allows use in commercial videos (Pixabay Music, Mixkit, Uppbeat with its credit line). For trending songs, point them to Douyin's in-app music with the 无BGM版.
- Never publish, log in, or press anything on Douyin for the user.
- Never edit or delete the user's footage. Never modify existing Jianying drafts (the `--draft` option only adds a new one).
