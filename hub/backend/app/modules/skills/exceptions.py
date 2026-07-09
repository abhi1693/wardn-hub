class SkillsError(Exception):
    pass


class SkillNotFoundError(SkillsError):
    pass


class SkillAuditNotFoundError(SkillsError):
    pass

