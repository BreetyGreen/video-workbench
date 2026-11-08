# Task 1 Dify visual transport report

Date: 2026-09-08

Scope was limited to `services/control-plane/app/adapters/dify.py`, the new
`services/control-plane/tests/test_dify_visual.py`, and this report. No live
network requests, cloud credentials, commit, push, pipeline, or workflow edits
were made.

## Implemented

- `analyze_tutorial(inputs, *, image_paths=None)` remains compatible with
  existing callers and never mutates caller inputs.
- Tutorial configuration is required before any upload. `last_usage` is reset
  before validation or requests.
- All images are validated before the first request: maximum 8 files, bounded
  read of 2 MiB + 1 byte, maximum accepted size 2 MiB, decoded JPEG/PNG only,
  and maximum dimension 4096 pixels. Pillow decompression-bomb errors are
  normalized to `ValueError` without exposing local paths.
- Valid images are uploaded once each to `files/upload` as multipart data with
  sanitized sequential names (`frame-001.jpg` / `.png`), tutorial bearer auth,
  and user `automated-video-workbench`.
- Only validated upload IDs populate `inputs.visual_frames` using Dify's
  `image` / `local_file` / `upload_file_id` shape. Missing/blank IDs stop before
  workflow execution. Caller-supplied `visual_frames` are removed when no
  validated `image_paths` are supplied.
- Upload and workflow calls are not retried. An upload HTTP error stops the
  workflow call.
- Workflow usage tolerates malformed numeric fields, and run IDs are read in
  this order: top-level `workflow_run_id`, `data.id`, legacy
  `data.workflow_run_id`. A returned failed/stopped status raises only after
  preserving returned usage and before parsing/trusting outputs.

## TDD evidence

Initial RED command:

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
.\services\control-plane\.venv\Scripts\pytest.exe services\control-plane\tests\test_dify_visual.py -q
```

Result: exit code 1, `14 failed`; primary expected failure was
`TypeError: DifyClient.analyze_tutorial() got an unexpected keyword argument
'image_paths'`, with additional expected failures for new response behavior.

Review RED command for removal of untrusted caller file input:

```powershell
.\services\control-plane\.venv\Scripts\pytest.exe services\control-plane\tests\test_dify_visual.py::test_tutorial_without_images_sends_no_files_input -q
```

Result: exit code 1, `1 failed`; the request still contained caller-supplied
`visual_frames`. The implementation was changed to remove it and add only IDs
created by this validated upload path.

Bounded-read safety RED command:

```powershell
.\services\control-plane\.venv\Scripts\pytest.exe services\control-plane\tests\test_dify_visual.py::test_image_validation_uses_a_bounded_read services\control-plane\tests\test_dify_visual.py::test_decompression_bomb_is_reported_as_invalid_image -q
```

Result: exit code 1, `2 failed`; one proved unbounded `Path.read_bytes()` was
used and the other showed `Image.DecompressionBombError` escaped directly.

Final GREEN and static verification:

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
.\services\control-plane\.venv\Scripts\pytest.exe services\control-plane\tests\test_dify.py services\control-plane\tests\test_dify_visual.py -q
.\services\control-plane\.venv\Scripts\python.exe -m py_compile services\control-plane\app\adapters\dify.py services\control-plane\tests\test_dify_visual.py
git diff --check -- services/control-plane/app/adapters/dify.py services/control-plane/tests/test_dify_visual.py
```

Result: exit code 0, `23 passed in 1.74s`; compilation and diff checks also
returned exit code 0. Git emitted only its Windows LF-to-CRLF advisory.

## Evidence boundary

The tests exercise real Pillow-generated image bytes and HTTP requests through
`httpx.MockTransport`, including multipart bodies and exact workflow file ID
lists. They verify local transport behavior only. They do not prove a published
Dify workflow accepts the field, that a model receives or understands images,
or that semantic, product-claim, style, or native-playback quality passes.

## Reviewer follow-up evidence

Pixel decoding review RED:

```powershell
.\services\control-plane\.venv\Scripts\pytest.exe services\control-plane\tests\test_dify_visual.py::test_truncated_jpeg_is_rejected_before_any_request -q
```

Result: exit code 1, `1 failed`. A 64 x 64 JPEG truncated by 40 bytes passed
`Image.verify()` and reached `files/upload`. Validation now calls `image.load()`
after format and dimension bounds, so the actual pixels must decode before any
request.

Workflow status propagation RED:

```powershell
.\services\control-plane\.venv\Scripts\pytest.exe services\control-plane\tests\test_dify_visual.py::test_failed_workflow_retains_usage_but_does_not_trust_outputs services\control-plane\tests\test_dify_visual.py::test_stopped_workflow_retains_returned_status_in_usage -q
```

Result: exit code 1, `2 failed`, because `WorkflowUsage` did not expose the
returned terminal status. A trailing `status` field now preserves positional
compatibility, defaults legacy status-less successful replies to `succeeded`,
and records returned `failed` / `stopped` values before raising.

Fresh final verification after both reviewer fixes:

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
.\services\control-plane\.venv\Scripts\pytest.exe services\control-plane\tests\test_dify.py services\control-plane\tests\test_dify_visual.py -q
.\services\control-plane\.venv\Scripts\python.exe -m py_compile services\control-plane\app\adapters\dify.py services\control-plane\tests\test_dify_visual.py
git diff --check -- services/control-plane/app/adapters/dify.py services/control-plane/tests/test_dify_visual.py
```

Result: exit code 0, `25 passed in 2.91s`; compilation and diff checks returned
exit code 0, with only Git's Windows LF-to-CRLF advisory.
