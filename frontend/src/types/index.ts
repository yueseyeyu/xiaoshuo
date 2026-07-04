/**
 * 全局类型定义 — 世界推演引擎 (WSE) 核心数据模型
 *
 * 与后端 project_service.py schema v1.2.0 对齐
 */

// ============================================================
// 项目元数据
// ============================================================

export interface ProjectMeta {
  title: string;
  author: string;
  genre: string;
  volumes_count: number;
  total_chapters: number;
  written_chapters: number;
  summary: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectListItem {
  id: string;
  title: string;
  author: string;
  genre: string;
  volumes_count: number;
  total_chapters: number;
  written_chapters: number;
  is_demo: boolean;
  updated_at: string;
}

export interface Project {
  id: string;
  schema_version: string;
  is_demo: boolean;
  meta: ProjectMeta;
  skeleton: ProjectSkeleton;
  world: WorldInfo;
  characters: Character[];
  factions: Faction[];
  chapters: Chapter[];
  world_state?: WorldState;
}

export interface ProjectSkeleton {
  volumes: Volume[];
  chapters: SkeletonChapter[];
}

export interface Volume {
  title: string;
  subtitle: string;
  chapters: string; // "1-60"
  range?: string;   // 卷范围描述
  summary?: string; // 卷摘要
  tags?: string[];  // 卷标签
}

export interface SkeletonChapter {
  title: string;
  goal: string;
  conflict: string;
  result: string;
  hook: string;
  pleasure: string;
  foreshadowing: string;
  expectation: string;
  scenes: unknown[];
}

export interface WorldInfo {
  core: string;
  powers: string;
}

export interface Chapter {
  num: number;
  title: string;
  content: string;
  word_count: number;
}

// ============================================================
// 势力 (Faction) — WSE 核心实体
// ============================================================

export interface Faction {
  id: string;
  name: string;
  type: string; // 宗门/帝国/组织/部落
  region_id?: string;
  desc: string;
  /** 动态状态层 (v1.2 新增) */
  state?: FactionState;
  /** 内部层级结构 */
  hierarchy?: FactionMember[];
  /** 对外关系 */
  relations?: FactionRelation[];
  /** 近期事件 */
  recent_events?: FactionEvent[];
}

export interface FactionState {
  stability: number;   // 0-1 内部稳定度
  morale: number;      // 0-1 士气
  treasury: number;    // 0-1 财政
  threat_level: number; // 0-1 外部威胁
  power_level: number;  // 1-10 综合等级
}

/** 后端 world_state.factions_state 数组元素类型（含 id/name 标识） */
export interface FactionRuntimeState {
  id: string;
  name: string;
  stability: number;
  morale: number;
  treasury: number;
  threat_level: number;
  power_level: number;
}

export interface FactionMember {
  level: string;       // 宗主/长老/弟子
  character_id: string;
  authority: number;   // 0-100
}

export interface FactionRelation {
  target_id: string;
  type: 'ally' | 'hostile' | 'neutral' | 'trade' | 'vassal';
  intensity: number;   // 1-10
  reason: string;
}

export interface FactionEvent {
  event_id: string;
  type: string;        // internal_power_struggle / war / alliance / ...
  impact: number;      // -1 to 1
  chapter: number;
  description: string;
}

// ============================================================
// 角色 (Character) — 扩展运行时状态
// ============================================================

export interface Character {
  name: string;
  role: string;        // 主角/同伴/反派/配角
  identity: string;
  personality: string;
  ability: string;
  desc: string;
  /** 运行时状态 (v1.2 新增) */
  dynamic_state?: CharacterState;
}

export interface CharacterState {
  /** 运行时状态数组中包含 name 字段用于标识角色 */
  name?: string;
  faction_id?: string;
  health: number;      // 0-1
  mood: string;        // normal/angry/fearful/confident/...
  location: string;
  recent_actions: string[];
}

// ============================================================
// 地域 (Region) — WSE 第一层
// ============================================================

export interface Region {
  id: string;
  name: string;
  features: string;    // 地理特征
  culture: string;     // 文化底色
  adjacent_regions: string[]; // 相邻地域 ID
}

// ============================================================
// 世界状态快照 (WorldSnapshot) — 推演核心
// ============================================================

export interface WorldState {
  chapter: number;
  regions: Region[];
  /** 后端返回字段名为 factions_state（运行时状态数组，含 id/name/stability/morale 等） */
  factions_state: FactionRuntimeState[];
  characters_state: CharacterState[];
  snapshots: WorldSnapshot[];
}

export interface WorldSnapshot {
  chapter: number;
  timestamp: string;
  factions_state: FactionRuntimeState[];
  characters_state: CharacterState[];
  events: SimulationEvent[];
}

// ============================================================
// 推演事件
// ============================================================

export interface SimulationEvent {
  id: string;
  chapter: number;
  round: number;
  type: 'character_action' | 'faction_decision' | 'impact_propagation' | 'conflict_detected';
  actor: string;       // 角色/势力 ID
  description: string;
  effects: StateChange[];
}

export interface StateChange {
  target_type: 'faction' | 'character';
  target_id: string;
  field: string;       // stability/morale/health/...
  delta: number;       // 变化量
  reason: string;
}

// ============================================================
// API 通用响应
// ============================================================

export interface ApiResponse<T> {
  ok: boolean;
  data?: T;
  error?: string;
}

export interface ProjectsResponse {
  projects: ProjectListItem[];
}

export interface FactionsResponse {
  factions: Faction[];
}

export interface CharactersResponse {
  characters: Character[];
}
