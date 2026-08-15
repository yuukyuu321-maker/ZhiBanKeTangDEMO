"""Deterministic builders for legacy and multi-session lesson-plan drafts."""

from __future__ import annotations

from .lesson_plan_v2 import (
    LessonExperiment,
    LessonPlanContent,
    TopicCoverageStatus,
    TopicEvidenceCoverage,
)
from .planning import LessonSegment, LessonSession, LessonSessionKind, SegmentPriority


def build_deterministic_lesson_plan(
    *,
    title: str,
    objectives: tuple[str, ...],
    required_topics: tuple[str, ...],
    lesson_count: int,
    minutes_per_lesson: int,
    evidence_ids: tuple[str, ...],
    preserve_experiment: bool,
    sessions: tuple[LessonSession, ...] = (),
    topic_coverage: tuple[TopicEvidenceCoverage, ...] = (),
    experiments: tuple[LessonExperiment, ...] = (),
) -> LessonPlanContent:
    if lesson_count <= 0 or minutes_per_lesson <= 0:
        raise ValueError("lesson count and minutes must be positive")
    if not evidence_ids:
        raise ValueError("lesson plan generation requires textbook evidence")
    if not sessions:
        return _build_legacy_plan(
            title=title,
            objectives=objectives,
            required_topics=required_topics,
            lesson_count=lesson_count,
            minutes_per_lesson=minutes_per_lesson,
            evidence_ids=evidence_ids,
            preserve_experiment=preserve_experiment,
        )
    if not topic_coverage:
        raise ValueError("multi-session planning requires topic evidence coverage")
    if tuple(item.title for item in topic_coverage) != required_topics:
        raise ValueError("topic coverage must preserve required topic order")
    segments = _build_multi_session_segments(
        sessions=sessions,
        topic_coverage=topic_coverage,
        experiments=experiments,
        fallback_evidence_ids=evidence_ids,
    )
    omissions = tuple(
        f"{item.title}：{item.notes or '教材证据不足，需教师补充并确认来源。'}"
        for item in topic_coverage
        if item.status is not TopicCoverageStatus.COVERED
    )
    return LessonPlanContent(
        title=title,
        objectives=objectives,
        required_topics=required_topics,
        available_minutes=sum(item.minutes for item in sessions),
        lesson_segments=segments,
        board_plan=tuple(f"{item.title}（{item.minutes} 分钟）" for item in sessions),
        checks_for_understanding=(
            "每个必讲知识点是否已定位到对应教材或经确认的补充来源？",
            "各实验的装置、步骤、现象、结论和误差是否能由学生说明？",
            "连续学生实验的气密性检测、制取和收集是否按教师确认顺序完成？",
        ),
        materials=(
            "已固定教材与逐知识点证据页",
            "教师提供且已登记来源的补充材料（如教材未覆盖）",
            "实验器材、药品、个人防护与废弃物处理条件（教师确认）",
        ),
        omissions=omissions,
        limitations=(
            "当前为离线确定性结构草稿；教师须核对教材原页、补充材料来源、实验安全和课堂适用性。",
            "知识点覆盖状态由教师复核；证据不足的必讲内容会阻止确认。",
            "未保存或展示模型隐藏思维链；仅保留可审查的教学步骤与证据标识。",
        ),
        sessions=sessions,
        topic_coverage=topic_coverage,
        experiments=experiments,
    )


def _build_legacy_plan(
    *,
    title: str,
    objectives: tuple[str, ...],
    required_topics: tuple[str, ...],
    lesson_count: int,
    minutes_per_lesson: int,
    evidence_ids: tuple[str, ...],
    preserve_experiment: bool,
) -> LessonPlanContent:
    available = lesson_count * minutes_per_lesson
    definitions = [
        (
            "opening",
            "问题导入",
            3,
            SegmentPriority.REQUIRED,
            "提出课题相关问题，并说明结论需要核对所选教材证据。",
            "观察问题、表达已有认识并记录待验证观点。",
        ),
        (
            "evidence-explanation",
            "教材证据讲解",
            10,
            SegmentPriority.REQUIRED,
            "打开所选教材证据，按原页顺序组织讲解并保留核对入口。",
            "阅读证据原文，提取关键信息并用自己的语言复述。",
        ),
    ]
    if preserve_experiment:
        definitions.append(
            (
                "experiment",
                "实验探究",
                15,
                SegmentPriority.REQUIRED,
                "依据教师确认的教材步骤、学校安全要求和现有条件组织实验。",
                "按教师确认的步骤观察、记录并讨论实验现象。",
            )
        )
    definitions.append(
        (
            "summary-check",
            "总结与检查",
            7,
            SegmentPriority.RECOMMENDED,
            "回到所选教材证据总结本课，并检查学生是否能够定位依据。",
            "完成课堂检查，说明答案对应的教材证据。",
        )
    )
    weights = tuple(item[2] for item in definitions)
    target = max(len(definitions), min(available, round(available * 0.875)))
    minutes = _allocate_minutes(target, weights)
    segments = tuple(
        LessonSegment(
            title=item[1],
            minutes=segment_minutes,
            priority=item[3],
            evidence_ids=evidence_ids,
            segment_id=item[0],
            teacher_activity=item[4],
            student_activity=item[5],
            locked=item[0] == "experiment" and preserve_experiment,
        )
        for item, segment_minutes in zip(definitions, minutes, strict=True)
    )
    return LessonPlanContent(
        title=title,
        objectives=objectives,
        required_topics=required_topics,
        available_minutes=available,
        lesson_segments=segments,
        board_plan=("课题与目标", "教材证据要点", "探究记录", "课堂总结"),
        checks_for_understanding=(
            "学生能否指出结论对应的教材页与证据区域？",
            "学生能否用可审查步骤说明本课关键内容？",
        ),
        materials=(
            "已固定教材与所选证据页",
            "实验材料与安全条件（由教师依据教材和学校要求确认）",
        ),
        limitations=(
            "当前为离线确定性模板草稿；教师须核对教材原页、实验安全要求和课堂适用性。",
            "未保存或展示模型隐藏思维链；仅保留可审查的教学步骤与教材证据标识。",
        ),
    )


def _build_multi_session_segments(
    *,
    sessions: tuple[LessonSession, ...],
    topic_coverage: tuple[TopicEvidenceCoverage, ...],
    experiments: tuple[LessonExperiment, ...],
    fallback_evidence_ids: tuple[str, ...],
) -> tuple[LessonSegment, ...]:
    session_ids = {item.session_id for item in sessions}
    topic_ids = {item.topic_id for item in topic_coverage}
    for experiment in experiments:
        if experiment.session_id not in session_ids:
            raise ValueError("experiment references an unknown session")
        if set(experiment.topic_ids) - topic_ids:
            raise ValueError("experiment references an unknown topic")
    experiment_topics = {topic_id for item in experiments for topic_id in item.topic_ids}
    instructional_topics = [
        item
        for item in topic_coverage
        if item.evidence_ids and item.topic_id not in experiment_topics
    ]
    instructional_sessions = [
        item for item in sessions if item.kind is not LessonSessionKind.STUDENT_LAB
    ]
    if instructional_topics and not instructional_sessions:
        raise ValueError("instructional topics require a non-lab session")
    topic_groups: dict[str, list[TopicEvidenceCoverage]] = {
        item.session_id: [] for item in sessions
    }
    for index, topic in enumerate(instructional_topics):
        target = instructional_sessions[
            min(
                len(instructional_sessions) - 1,
                index * len(instructional_sessions) // len(instructional_topics),
            )
        ]
        topic_groups[target.session_id].append(topic)

    experiments_by_session: dict[str, list[LessonExperiment]] = {
        item.session_id: [] for item in sessions
    }
    for experiment in experiments:
        experiments_by_session[experiment.session_id].append(experiment)

    first_instruction = instructional_sessions[0].session_id if instructional_sessions else ""
    last_instruction = instructional_sessions[-1].session_id if instructional_sessions else ""
    segments: list[LessonSegment] = []
    fallback = tuple(dict.fromkeys(fallback_evidence_ids))
    for session in sessions:
        fixed_experiments = experiments_by_session[session.session_id]
        fixed_minutes = sum(item.minutes for item in fixed_experiments)
        structural_count = int(session.session_id == first_instruction) + int(
            session.session_id == last_instruction
        )
        group = topic_groups[session.session_id]
        dynamic_count = structural_count + int(bool(group))
        target = max(
            fixed_minutes + dynamic_count,
            min(session.minutes, round(session.minutes * 0.9)),
        )
        dynamic_minutes = (
            _allocate_minutes(
                max(dynamic_count, target - fixed_minutes),
                tuple([3] * dynamic_count),
            )
            if dynamic_count
            else ()
        )
        dynamic_index = 0
        if session.session_id == first_instruction:
            segments.append(
                LessonSegment(
                    title="任务与证据导入",
                    minutes=dynamic_minutes[dynamic_index],
                    priority=SegmentPriority.REQUIRED,
                    evidence_ids=fallback,
                    segment_id=f"{session.session_id}-opening",
                    teacher_activity="呈现课题、课时结构和证据边界，说明教材未覆盖内容不得由模型补写。",
                    student_activity="提出已有认识，标记需要通过实验或教材证据验证的问题。",
                    session_id=session.session_id,
                )
            )
            dynamic_index += 1
        if group:
            group_evidence = tuple(
                dict.fromkeys(evidence_id for item in group for evidence_id in item.evidence_ids)
            )
            segments.append(
                LessonSegment(
                    title="知识点推进：" + "、".join(item.title for item in group),
                    minutes=dynamic_minutes[dynamic_index],
                    priority=SegmentPriority.REQUIRED,
                    evidence_ids=group_evidence,
                    segment_id=f"{session.session_id}-topics",
                    teacher_activity="按照教师给定顺序，以生活现象、前序实验问题和知识内在联系完成衔接。",
                    student_activity="核对原页证据，记录现象—原因—结论之间的关系。",
                    session_id=session.session_id,
                    topic_ids=tuple(item.topic_id for item in group),
                )
            )
            dynamic_index += 1
        for experiment in fixed_experiments:
            segments.append(
                LessonSegment(
                    title=experiment.title,
                    minutes=experiment.minutes,
                    priority=SegmentPriority.REQUIRED,
                    evidence_ids=experiment.evidence_ids,
                    segment_id=experiment.experiment_id,
                    teacher_activity="按已登记证据、学校实验安全要求和教师确认步骤组织实验。",
                    student_activity="完成观察或操作，记录装置、步骤、现象、结论和误差。",
                    locked=True,
                    session_id=session.session_id,
                    topic_ids=experiment.topic_ids,
                )
            )
        if session.session_id == last_instruction:
            segments.append(
                LessonSegment(
                    title="跨课时总结与检查",
                    minutes=dynamic_minutes[dynamic_index],
                    priority=SegmentPriority.RECOMMENDED,
                    evidence_ids=fallback,
                    segment_id=f"{session.session_id}-summary",
                    teacher_activity="按必讲知识点逐项检查证据覆盖、实验结论和仍需补充的来源。",
                    student_activity="用可审查步骤复述关键结论，并指出对应证据或实验记录。",
                    session_id=session.session_id,
                )
            )
    return tuple(segments)


def _allocate_minutes(target: int, weights: tuple[int, ...]) -> tuple[int, ...]:
    if not weights:
        return ()
    if target < len(weights):
        raise ValueError("available lesson time is too short for the required structure")
    total_weight = sum(weights)
    allocated = [max(1, target * weight // total_weight) for weight in weights]
    while sum(allocated) < target:
        index = max(
            range(len(weights)),
            key=lambda item: (target * weights[item] / total_weight) - allocated[item],
        )
        allocated[index] += 1
    while sum(allocated) > target:
        index = max(range(len(weights)), key=lambda item: allocated[item])
        if allocated[index] <= 1:
            raise ValueError("could not allocate lesson minutes")
        allocated[index] -= 1
    return tuple(allocated)
