const assert = require("node:assert/strict");
const { test } = require("node:test");

const {
  createEmptyOcrPreviewState,
  createOcrPreviewRequestTracker,
} = require("../web/ocr-preview-state.js");

test("OCR preview reset clears candidates and text and disables confirmation", () => {
  const state = createEmptyOcrPreviewState();

  assert.deepEqual(state, {
    candidates: [],
    text: "",
    confirmDisabled: true,
  });
});

test("OCR preview reset returns fresh candidate storage each time", () => {
  const first = createEmptyOcrPreviewState();
  first.candidates.push({ subject: "数学", score_candidate: 80 });

  const second = createEmptyOcrPreviewState();

  assert.deepEqual(second.candidates, []);
  assert.notStrictEqual(first.candidates, second.candidates);
});

test("a newer OCR preview request makes an older response stale", () => {
  const tracker = createOcrPreviewRequestTracker();

  const firstRequest = tracker.begin();
  const secondRequest = tracker.begin();

  assert.equal(tracker.isCurrent(firstRequest), false);
  assert.equal(tracker.isCurrent(secondRequest), true);
});

test("changing the selected PDF invalidates an in-flight OCR response", () => {
  const tracker = createOcrPreviewRequestTracker();
  const request = tracker.begin();

  tracker.invalidate();

  assert.equal(tracker.isCurrent(request), false);
});
