const assert = require("node:assert/strict");
const { test } = require("node:test");

const {
  createEmptyOcrPreviewState,
  createOcrPreviewRequestTracker,
  runOcrConfirmationFlow,
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


test("OCR save failure preserves the review state and does not refresh", async () => {
  let cleared = false;
  let refreshed = false;
  let notified = false;

  await assert.rejects(
    runOcrConfirmationFlow({
      submit: async () => {
        throw new Error("保存に失敗しました");
      },
      clearPreview: () => {
        cleared = true;
      },
      refresh: async () => {
        refreshed = true;
      },
      notifySaved: () => {
        notified = true;
      },
      notifyRefreshFailure: () => {
        notified = true;
      },
    }),
    /保存に失敗しました/,
  );

  assert.equal(cleared, false);
  assert.equal(refreshed, false);
  assert.equal(notified, false);
});

test("OCR save remains successful when refreshing the dashboard fails", async () => {
  const result = { imported: 2, duplicates: 1 };
  const refreshError = new Error("dashboard unavailable");
  const events = [];

  const returned = await runOcrConfirmationFlow({
    submit: async () => {
      events.push("submit");
      return result;
    },
    clearPreview: () => events.push("clear"),
    refresh: async () => {
      events.push("refresh");
      throw refreshError;
    },
    notifySaved: () => events.push("saved"),
    notifyRefreshFailure: (savedResult, error) => {
      events.push(["refresh-failed", savedResult, error]);
    },
  });

  assert.equal(returned, result);
  assert.deepEqual(events, [
    "submit",
    "clear",
    "refresh",
    ["refresh-failed", result, refreshError],
  ]);
});

test("OCR success notification is shown only after dashboard refresh", async () => {
  const events = [];
  const result = { imported: 1, duplicates: 0 };

  await runOcrConfirmationFlow({
    submit: async () => {
      events.push("submit");
      return result;
    },
    clearPreview: () => events.push("clear"),
    refresh: async () => events.push("refresh"),
    notifySaved: savedResult => events.push(["saved", savedResult]),
    notifyRefreshFailure: () => events.push("refresh-failed"),
  });

  assert.deepEqual(events, [
    "submit",
    "clear",
    "refresh",
    ["saved", result],
  ]);
});
