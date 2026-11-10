const assert = require("node:assert/strict");
const { test } = require("node:test");

const {
  createEmptyOcrPreviewState,
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
