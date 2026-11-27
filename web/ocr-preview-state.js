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


  async function runOcrConfirmationFlow({
    submit,
    clearPreview,
    refresh,
    notifySaved,
    notifyRefreshFailure,
  }) {
    const result = await submit();
    clearPreview();

    try {
      await refresh();
      notifySaved(result);
    } catch (error) {
      notifyRefreshFailure(result, error);
    }

    return result;
  }

  root.createEmptyOcrPreviewState = createEmptyOcrPreviewState;
  root.createOcrPreviewRequestTracker = createOcrPreviewRequestTracker;
  root.runOcrConfirmationFlow = runOcrConfirmationFlow;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      createEmptyOcrPreviewState,
      createOcrPreviewRequestTracker,
      runOcrConfirmationFlow,
    };
  }
})(typeof window !== "undefined" ? window : globalThis);
