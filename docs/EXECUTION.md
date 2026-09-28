# Execution Sessions and Timer Reconstruction

## Client countdown

For a running segment the client receives the Focus Plan snapshot, `currentSegmentIndex`, `currentSegmentStartedAt`, and Session `version`.

For a fixed target:

```text
activeElapsed = serverNow - currentSegmentStartedAt
remaining = targetSeconds - activeElapsed
```

`currentSegmentStartedAt` is adjusted on resume, so manual pauses are excluded. A negative `remaining` means the target has been exceeded; it does not imply the segment or Session was automatically completed.

When `currentSegmentStartedAt` is null, the Session is between segments. The client should offer the appropriate start action and submit `segment_started` or `break_started`.

## Cross-device rules

1. Refetch `/execution-sessions/active` when the application gains focus.
2. Poll lightly while a Session is open if realtime transport is not available.
3. Send `If-Match` from the latest Session ETag for every Event mutation.
4. Give every mutation a stable client-generated `Idempotency-Key` and reuse it for transport retries only.
5. On `412`, discard the stale local mutation assumption, refetch server truth and let the user resolve any conflict.

No websocket is required for v1 correctness.

## Event semantics

- `paused`: running → paused.
- `resumed`: paused → running and shifts the active segment anchor by the pause duration.
- `segment_started`: starts the current non-break segment; it cannot restart an already active segment.
- `segment_completed`: ends the current non-break segment and advances to the next, which remains unstarted.
- `segment_skipped`: allowed only for an optional current segment; advances without fabricating work time.
- `break_started`: starts the current break/long-break segment.
- `break_ended`: ends the current break and advances.
- `work_item_completed`: explicitly completes the Session Chore or an eligible direct child Chore of a Sprint.
- `session_completed`: terminal successful Session outcome, including finish-early use cases.
- `session_abandoned`: terminal abandoned outcome.

## Persistence and restarts

There is no countdown process to lose. After a backend restart, the Session row and Event stream contain everything required to render the same state. Round 6 analytics derives active-work, break and paused intervals from these authoritative records; no in-memory timer history is required.
