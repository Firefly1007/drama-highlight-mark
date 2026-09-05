"""即时投票 Specialist。"""

from drama_interaction.specialists.base import BaseSpecialist


class InstantVoteSpecialist(BaseSpecialist):
    """将当前证据已明确的冲突或选择生成二选一投票。"""

    specialist_type = "instant_vote"
