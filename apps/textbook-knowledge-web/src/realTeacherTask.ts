import type {
  LessonPlanGenerationConfig,
  TopicEvidenceCoverage,
} from "./api";

const topics: TopicEvidenceCoverage[] = [
  {
    topic_id: "topic-1",
    title: "拉瓦锡实验及原理分析",
    status: "covered",
    evidence_ids: ["ev_bef37ca728f4b9a8b1e74524", "ev_cffd063da1af2dd04017b70e"],
    notes: "教材第 2 页：拉瓦锡实验过程、现象与结论。",
  },
  {
    topic_id: "topic-2",
    title: "实验重构",
    status: "covered",
    evidence_ids: ["ev_2134780b4b2d0fa7aab0773a", "ev_f09ba0079693b3c6ed1e79c1"],
    notes: "教材第 3 页：仿照拉瓦锡原理的红磷实验。",
  },
  {
    topic_id: "topic-3",
    title: "通过重构实验验证空气中氧气含量",
    status: "covered",
    evidence_ids: ["ev_f09ba0079693b3c6ed1e79c1", "ev_35477f7a247571dc93cb37f1"],
    notes: "教材第 3 页：操作、原理与约五分之一的结论。",
  },
  {
    topic_id: "topic-4",
    title: "实验误差来源分析",
    status: "covered",
    evidence_ids: ["ev_f09ba0079693b3c6ed1e79c1", "ev_c705d0f354254fb7c3f363bf"],
    notes: "教材第 3、11 页：可靠性分析与减小误差问题。",
  },
  {
    topic_id: "topic-5",
    title: "空气成分",
    status: "covered",
    evidence_ids: ["ev_35477f7a247571dc93cb37f1"],
    notes: "教材第 3 页：氮气、氧气及其他气体的体积分数。",
  },
  {
    topic_id: "topic-6",
    title: "氧气的性质（物理和化学）",
    status: "covered",
    evidence_ids: [
      "ev_c1096d618b301d90b64ba2ed",
      "ev_00e0cfd16d448f2061744e86",
      "ev_79c3c69ad1e6887e77d4fe89",
    ],
    notes: "教材第 5、7 页：氧气物理性质、化学活泼性和氧化性。",
  },
  {
    topic_id: "topic-7",
    title: "代表性物质与氧气的反应",
    status: "covered",
    evidence_ids: [
      "ev_2ec24a2ebd18e8a468625b53",
      "ev_0266a649f722605de5412f2d",
      "ev_ae8e43a39409030a7d079c93",
      "ev_3ffb0f2c92a2d08bbca97118",
    ],
    notes: "教材第 6、7 页：木条、硫和铁丝在氧气中的实验与结论。",
  },
  {
    topic_id: "topic-8",
    title: "氧气的制取（工业与三种实验室制法）",
    status: "partial",
    evidence_ids: [
      "ev_1b60751134ecfb912cb6bacc",
      "ev_7566b2f4ee44f64d645c343d",
      "ev_643d40fa4d145399566c8d2a",
      "ev_c3f8380675c6ca05af799ec6",
    ],
    notes:
      "教材覆盖工业法、过氧化氢法和氯酸钾法；高锰酸钾法来自教师补充图片，尚未登记为工作区证据。",
  },
  {
    topic_id: "topic-9",
    title: "气体收集方式与实验装置连接",
    status: "partial",
    evidence_ids: ["ev_643d40fa4d145399566c8d2a", "ev_8cb196425a7779bf6c2f2260"],
    notes: "教材第 8、9 页覆盖装置连接与排水收集；尚未定位向上排空气法证据。",
  },
  {
    topic_id: "topic-10",
    title: "气密性检测",
    status: "covered",
    evidence_ids: ["ev_8cb196425a7779bf6c2f2260"],
    notes: "教材第 9 页：关闭活塞、浸水、手握瓶壁并观察气泡和水柱。",
  },
  {
    topic_id: "topic-11",
    title: "实验操作注意事项与错误操作识别",
    status: "partial",
    evidence_ids: ["ev_8cb196425a7779bf6c2f2260"],
    notes: "教材覆盖正确操作步骤；针对错误装置图的专项材料尚未登记。",
  },
  {
    topic_id: "topic-12",
    title: "催化剂定义与作用",
    status: "covered",
    evidence_ids: ["ev_93059e646b1406ad430807b8"],
    notes: "教材第 9 页：催化剂定义及二氧化锰的作用。",
  },
  {
    topic_id: "topic-13",
    title: "化合反应与分解反应",
    status: "covered",
    evidence_ids: ["ev_d5907c973f7b837b058c8494"],
    notes: "教材第 11 页：两类反应的定义和示例。",
  },
];

export const REAL_TEACHER_TASK_TITLE = "1.1 空气的成分";

export const REAL_TEACHER_TASK_EVIDENCE_IDS = [
  ...new Set(topics.flatMap((topic) => topic.evidence_ids)),
];

export const REAL_TEACHER_TASK_CONFIG: LessonPlanGenerationConfig = {
  objectives: ["按教材证据和实验链路完成空气与氧气单元学习"],
  requiredTopics: topics.map((topic) => topic.title),
  lessonCount: 4,
  minutesPerLesson: 40,
  preserveExperiment: true,
  instruction:
    "总计约 140 分钟；保留教师演示，并安排 40 分钟连续学生实验完成制氧、气密性检测和排水收集。",
  sessions: [
    { session_id: "lecture-1", title: "空气含量与实验重构", minutes: 40, kind: "mixed" },
    { session_id: "lecture-2", title: "氧气性质与代表性反应", minutes: 40, kind: "mixed" },
    { session_id: "lecture-3", title: "制取方法与反应类型", minutes: 20, kind: "demonstration" },
    { session_id: "student-lab", title: "制氧连续学生实验", minutes: 40, kind: "student_lab" },
  ],
  topicCoverage: topics,
  experiments: [
    {
      experiment_id: "experiment-air-content",
      title: "空气中氧气含量重构实验",
      session_id: "lecture-1",
      minutes: 12,
      mode: "demonstration_and_student",
      topic_ids: ["topic-3"],
      evidence_ids: ["ev_f09ba0079693b3c6ed1e79c1", "ev_35477f7a247571dc93cb37f1"],
      integrated_steps: ["装置确认", "反应与冷却", "读数", "误差分析"],
      safety_notes: ["教师确认药品、点燃、密闭和冷却条件"],
      teacher_safety_confirmed: false,
    },
    {
      experiment_id: "experiment-oxygen-reactions",
      title: "代表性物质与氧气反应",
      session_id: "lecture-2",
      minutes: 14,
      mode: "demonstration_and_student",
      topic_ids: ["topic-7"],
      evidence_ids: [
        "ev_2ec24a2ebd18e8a468625b53",
        "ev_0266a649f722605de5412f2d",
        "ev_ae8e43a39409030a7d079c93",
        "ev_3ffb0f2c92a2d08bbca97118",
      ],
      integrated_steps: ["现象观察", "产物判断", "反应表达", "差异解释"],
      safety_notes: ["教师确认燃烧实验防护、瓶底保护和废气处理"],
      teacher_safety_confirmed: false,
    },
    {
      experiment_id: "experiment-integrated-oxygen-demo",
      title: "制氧—气密性检测—收集连续演示",
      session_id: "lecture-3",
      minutes: 12,
      mode: "demonstration",
      topic_ids: ["topic-8", "topic-9", "topic-10"],
      evidence_ids: [
        "ev_643d40fa4d145399566c8d2a",
        "ev_8cb196425a7779bf6c2f2260",
      ],
      integrated_steps: ["连接装置", "检查气密性", "制取氧气", "排水收集"],
      safety_notes: ["教师确认演示药品、装置、防护和废弃物处理"],
      teacher_safety_confirmed: false,
    },
    {
      experiment_id: "experiment-integrated-oxygen-lab",
      title: "制氧—气密性检测—收集连续学生实验",
      session_id: "student-lab",
      minutes: 40,
      mode: "student_lab",
      topic_ids: ["topic-8", "topic-9", "topic-10"],
      evidence_ids: [
        "ev_643d40fa4d145399566c8d2a",
        "ev_8cb196425a7779bf6c2f2260",
      ],
      integrated_steps: ["连接装置", "检查气密性", "加入药品", "制取氧气", "排水收集", "验满与整理"],
      safety_notes: ["教师确认学生实验药品浓度、装置、防护、废弃物处理和应急条件"],
      teacher_safety_confirmed: false,
    },
  ],
};
