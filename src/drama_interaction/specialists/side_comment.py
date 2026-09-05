"""边看边聊 Specialist。"""

from drama_interaction.specialists.base import BaseSpecialist


class SideCommentSpecialist(BaseSpecialist):
    """生成由当前集证据支撑的简短旁白评论。"""

    specialist_type = "side_comment"
