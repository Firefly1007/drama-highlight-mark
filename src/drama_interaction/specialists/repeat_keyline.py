"""跟读金句 Specialist。"""

from drama_interaction.specialists.base import BaseSpecialist


class RepeatKeylineSpecialist(BaseSpecialist):
    """从当前集台词中选择值得用户复述的原句。"""

    specialist_type = "repeat_keyline"
