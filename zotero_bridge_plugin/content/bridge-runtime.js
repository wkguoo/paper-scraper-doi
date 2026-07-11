(function () {
  const bridge = {
    timer: null,
    lastStatus: "插件已启动，尚无已处理批次。",

    async startup() {
      if (this.timer) return;
      this.timer = setInterval(() => {
        this.scanNow().catch(error => Zotero.logError(error));
      }, 1000);
    },

    async shutdown() {
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
    },

    async scanNow() {},

    showStatus() {
      Services.prompt.alert(null, "文献下载桥接", this.lastStatus);
    },

    async undoLastBatch() {
      Services.prompt.alert(null, "文献下载桥接", "当前没有可撤销的批次。");
    },
  };

  Zotero.PaperDownloadBridge = bridge;
})();
