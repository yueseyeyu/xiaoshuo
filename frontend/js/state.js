/**
 * 全局状态管理（最小化实现）
 */
export const state = {
    books: [],
    selected: new Set(),
    running: false,
    genre: "末世",
    hardware: null,
    alerts: [],
    pipelineStage: null,  // P1: current pipeline stage {stage, stage_num, total, status}

    toggleBook(name) {
        if (this.selected.has(name)) {
            this.selected.delete(name);
        } else {
            this.selected.add(name);
        }
    },

    selectAll() {
        this.selected = new Set(this.books.filter(b => !b.is_complete).map(b => b.name));
    },

    selectNone() {
        this.selected.clear();
    },
};
