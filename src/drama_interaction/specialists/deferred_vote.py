"""延时投票 Specialist。"""

from drama_interaction.specialists.base import BaseSpecialist


class DeferredVoteSpecialist(BaseSpecialist):
    """识别有可靠后续揭晓位置的剧情悬念。"""

    specialist_type = "deferred_vote"
