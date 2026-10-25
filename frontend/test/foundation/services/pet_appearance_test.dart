import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/models/current_pet.dart';
import 'package:kz_2607/foundation/models/pet_appearance.dart';
import 'package:kz_2607/foundation/models/pet_parts.dart';

void main() {
  final appearance = {
    'stage': 'baby',
    'primary': 'activity',
    'secondary': 'logical',
    'key': 'activity_logical_baby',
    'fallbackKey': 'activity_baby',
  };
  test(
    'uses server primary for body and secondary for eye and mouth assets',
    () {
      final parts = PetParts(PetAppearance.fromMap(appearance));
      expect(
        parts.animalAsset,
        'assets/pet_parts/animals/animal_activity_baby.png',
      );
      expect(parts.eyesAsset, 'assets/pet_parts/eyes/eyes_logical.png');
      expect(parts.mouthAsset, 'assets/pet_parts/mouth/mouth_04_smile.png');
    },
  );
  test('unknown or inconsistent artwork identifiers are rejected', () {
    expect(
      () => PetAppearance.fromMap({...appearance, 'key': '../other'}),
      throwsFormatException,
    );
    expect(
      () => PetAppearance.fromMap({...appearance, 'stage': 'unknown'}),
      throwsFormatException,
    );
  });
  test('born state and appearance survive getPet parsing', () {
    final pet = CurrentPet.fromMap({
      'petId': 'pet-a',
      'name': 'モチ',
      'generation': 1,
      'gauge': 0,
      'birthStatus': 'born',
      'appearance': appearance,
    });
    expect(pet.born, isTrue);
    expect(pet.appearance!.key, 'activity_logical_baby');
  });
}
