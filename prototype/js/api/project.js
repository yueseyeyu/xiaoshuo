"use strict";

// ============================================================
// Project API 客户端 — 创作作品（一书一档）
// ============================================================

const ProjectAPI = {
  // 项目列表
  async list(includeDemo = false) {
    const res = await apiGet(`/api/projects?include_demo=${includeDemo}`);
    return res.ok ? res.data : null;
  },

  // 创建项目（权重文件较大，超时放宽到 60 秒）
  async create(body = {}) {
    const res = await apiPost('/api/projects', body, 60000);
    return res.ok ? res.data : null;
  },

  // 从示例模板创建
  async createFromDemo(meta = {}) {
    return this.create({ from_demo: true, meta });
  },

  // 获取完整项目
  async get(projectId) {
    const res = await apiGet(`/api/projects/${projectId}`);
    return res.ok ? res.data : null;
  },

  // 更新项目元数据
  async updateMeta(projectId, meta) {
    const res = await apiPut(`/api/projects/${projectId}`, { meta });
    return res.ok ? res.data : null;
  },

  // 删除项目
  async delete(projectId) {
    const res = await apiDelete(`/api/projects/${projectId}`);
    return res.ok ? res.data : null;
  },

  // demo 转正
  async promote(projectId) {
    const res = await apiPost(`/api/projects/${projectId}/promote`);
    return res.ok ? res.data : null;
  },

  // 获取示例项目模板
  async getDemoTemplate() {
    const res = await apiGet('/api/projects/demo');
    return res.ok ? res.data : null;
  },

  // 粗纲/细纲
  async getSkeleton(projectId) {
    const res = await apiGet(`/api/projects/${projectId}/skeleton`);
    return res.ok ? res.data : null;
  },
  async updateSkeleton(projectId, skeleton) {
    const res = await apiPut(`/api/projects/${projectId}/skeleton`, skeleton);
    return res.ok ? res.data : null;
  },

  // 世界观
  async getWorld(projectId) {
    const res = await apiGet(`/api/projects/${projectId}/world`);
    return res.ok ? res.data : null;
  },
  async updateWorld(projectId, world) {
    const res = await apiPut(`/api/projects/${projectId}/world`, world);
    return res.ok ? res.data : null;
  },

  // 角色
  async getCharacters(projectId) {
    const res = await apiGet(`/api/projects/${projectId}/characters`);
    return res.ok ? res.data : null;
  },
  async updateCharacters(projectId, characters) {
    const res = await apiPut(`/api/projects/${projectId}/characters`, { characters });
    return res.ok ? res.data : null;
  },

  // 势力
  async getFactions(projectId) {
    const res = await apiGet(`/api/projects/${projectId}/factions`);
    return res.ok ? res.data : null;
  },
  async updateFactions(projectId, factions) {
    const res = await apiPut(`/api/projects/${projectId}/factions`, { factions });
    return res.ok ? res.data : null;
  },

  // 章节
  async getChapters(projectId) {
    const res = await apiGet(`/api/projects/${projectId}/chapters`);
    return res.ok ? res.data : null;
  },
  async getChapter(projectId, chapterNum) {
    const res = await apiGet(`/api/projects/${projectId}/chapters/${chapterNum}`);
    return res.ok ? res.data : null;
  },
  async updateChapter(projectId, chapterNum, chapter) {
    const res = await apiPut(`/api/projects/${projectId}/chapters/${chapterNum}`, chapter);
    return res.ok ? res.data : null;
  },
};
