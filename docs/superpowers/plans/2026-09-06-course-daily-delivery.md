# Course Daily Delivery Implementation Plan

**Goal:** Connect a chosen course, its material selection, daily time and receiving device to actual course-driven editing; provide a Mac setup application instead of requiring terminal installation.

**Architecture:** A dedicated persisted course schedule and run ledger reuse course intake, tutorial processing, CourseEditJobService and device delivery. The existing keyword automation stays independent. A server-rendered page manages courses and schedules. Mac setup wraps the existing sync executable and user LaunchAgent.

## Global constraints

- Preserve user data and existing drafts; do not print credentials.
- Local/cloud processing choice is explicit and defaults false. Commercial material selection remains enforced.
- A selected device is assigned before a job becomes visible; quality failure never delivers.
- Scheduled runs deduplicate by plan and local date; interrupted runs are surfaced, not silently duplicated.
- Public server, real DingTalk and real Mac GUI acceptance remain unverified until tested on those resources.
- Work in the existing isolated worktree on codex/course-daily-delivery.

### Task 1: Course schedule and user flow

- [x] Add separate CourseSchedule and CourseScheduleRun tables, schemas, service and router. Save course, material subset, brief, local daily time, timezone, optional target device and cloud consent.
- [x] Add tests for invalid course/device/material, disabled/due times, same-day duplicate runs, interrupted run status, quality failure and explicit device routing.
- [x] Execute existing course processing when recipe absent, then CourseEditJobService with frozen selection and device. Run asynchronously through persisted queue; preserve completed job links.
- [x] Provide /courses page for multipart tutorial/material intake, one-time/daily plan, pause, run now, status and preview links. Integrate sidebar/setup.
- [x] Verify tests, JS and browser behavior; run real renderer against existing demo course through schedule service in isolated validation state.

### Task 2: Mac graphical setup and packaging

- [x] Build a double-clickable Mac setup app, asking server URL and pairing code through native dialogs; pair without displaying/logging token.
- [x] Install bundled sync helper into user Applications, write LaunchAgent safely, show success only after successful pairing and launchctl start, support cancel/error without destructive cleanup.
- [x] Package app and helper into downloadable archive with hashes in macOS CI. Build 33979407461 passed for both platforms; artifacts are unsigned development builds.
- [x] Verify setup logic with focused non-Mac tests plus macOS build workflow; distinguish CI from real Mac acceptance.
- [ ] Configure an actual Apple signing identity/notarization profile on a trusted builder and verify Finder/LaunchAgent/Jianying on a real Mac. Optional build-script hooks exist, but no signing secrets or identities were provided.

### Task 3: Evidence, review and release

- [x] Update human guide, Codex guide, capability catalog and progress with current boundaries.
- [x] Review diff independently and fix substantive findings.
- [ ] Run appropriate regression, publish through existing authorized GitHub PR workflow, verify CI and default-branch state.
