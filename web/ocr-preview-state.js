(function (root) {
  function createEmptyOcrPreviewState() {
    return {
      candidates: [],
      text: "",
      confirmDisabled: true,
    };
  }

  function createOcrPreviewRequestTracker() {
    let currentRequest = 0;

    return {
      begin() {
        currentRequest += 1;
        return currentRequest;
      },
      invalidate() {
        currentRequest += 1;
      },
      isCurrent(requestId) {
        return requestId === currentRequest;
      },
    };
  }

  root.createEmptyOcrPreviewState = createEmptyOcrPreviewState;
  root.createOcrPreviewRequestTracker = createOcrPreviewRequestTracker;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      createEmptyOcrPreviewState,
      createOcrPreviewRequestTracker,
    };
  }
})(typeof window !== "undefined" ? window : globalThis);
