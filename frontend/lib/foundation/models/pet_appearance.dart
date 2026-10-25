/// Server-selected artwork identifiers. No personality ranking is done locally.
class PetAppearance {
  const PetAppearance({
    required this.stage,
    required this.primary,
    required this.secondary,
    required this.key,
    required this.fallbackKey,
    this.tertiary,
  });
  final String stage, primary, secondary, key, fallbackKey;
  final String? tertiary;
  static const axes = {
    'activity',
    'friendly',
    'talkative',
    'logical',
    'curious',
    'nightowl',
  };
  static const stages = {'baby', 'child', 'adult'};

  factory PetAppearance.fromMap(Map data) {
    final stage = data['stage'],
        primary = data['primary'],
        secondary = data['secondary'];
    if (!stages.contains(stage) ||
        !axes.contains(primary) ||
        !axes.contains(secondary) ||
        primary == secondary ||
        (data['tertiary'] != null &&
            (!axes.contains(data['tertiary']) ||
                data['tertiary'] == primary ||
                data['tertiary'] == secondary)) ||
        data['key'] != '${primary}_${secondary}_$stage' ||
        data['fallbackKey'] != '${primary}_$stage') {
      throw const FormatException('appearanceの画像指定が不正です');
    }
    return PetAppearance(
      tertiary: data['tertiary'] as String?,
      stage: stage as String,
      primary: primary as String,
      secondary: secondary as String,
      key: data['key'] as String,
      fallbackKey: data['fallbackKey'] as String,
    );
  }
}
