import 'pet_appearance.dart';

/// Frontend mapping: primary determines the body, secondary the eyes; tertiary selects the mouth when available.
/// Uses server-selected axes without re-ranking personality values.
class PetParts {
  const PetParts(this.appearance);
  final PetAppearance appearance;
  String get animalAsset =>
      'assets/pet_parts/animals/animal_${appearance.primary}_${appearance.stage}.png';
  String get eyesAsset =>
      'assets/pet_parts/eyes/eyes_${appearance.secondary}.png';
  String get mouthAxis => appearance.tertiary ?? appearance.secondary;
  String get mouthAsset => 'assets/pet_parts/mouth/${mouths[mouthAxis]!}';
  static const mouths = {
    'activity': 'mouth_01_open_smile.png',
    'friendly': 'mouth_02_cat.png',
    'talkative': 'mouth_03_open_o.png',
    'logical': 'mouth_04_smile.png',
    'curious': 'mouth_05_small_o.png',
    'nightowl': 'mouth_06_smile_side.png',
  };
}
