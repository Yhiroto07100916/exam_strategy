(function (root) {
  function createEmptyOcrPreviewState() {
    return {
      candidates: [],
      text: "",
      confirmDisabled: true,
    };
  }

  root.createEmptyOcrPreviewState = createEmptyOcrPreviewState;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { createEmptyOcrPreviewState };
  }
})(typeof window !== "undefined" ? window : globalThis);
