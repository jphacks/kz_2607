import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/models/pet_appearance.dart';
import 'package:kz_2607/foundation/models/pet_parts.dart';
import 'package:kz_2607/designsystem/pet_part_layout.dart';

void main() {
  test(
    'every server combination has three assets and face parts stay inside the body canvas',
    () {
      var combinations = 0;
      for (final stage in PetAppearance.stages) {
        for (final primary in PetAppearance.axes) {
          for (final secondary in PetAppearance.axes.where(
            (axis) => axis != primary,
          )) {
            final parts = PetParts(
              PetAppearance.fromMap({
                'stage': stage,
                'primary': primary,
                'secondary': secondary,
                'key': '${primary}_${secondary}_$stage',
                'fallbackKey': '${primary}_$stage',
              }),
            );
            for (final path in [
              parts.animalAsset,
              parts.eyesAsset,
              parts.mouthAsset,
            ]) {
              expect(File(path).existsSync(), isTrue, reason: path);
            }
            final layout = PetPartLayout.forPet(primary, stage);
            final eyeSource = PetPartLayout.eyeSizes[secondary]!;
            final scale =
                layout.eyeSpacing / PetPartLayout.eyeSeparations[secondary]!;
            final left = layout.eyeCenter.dx - eyeSource.width * scale / 2;
            final top =
                layout.eyeCenter.dy - PetPartLayout.eyeLine[secondary]! * scale;
            expect(left, greaterThanOrEqualTo(0));
            expect(top, greaterThanOrEqualTo(0));
            expect(
              left + eyeSource.width * scale,
              lessThanOrEqualTo(layout.size.width),
            );
            expect(
              top + eyeSource.height * scale,
              lessThanOrEqualTo(layout.size.height),
            );
            expect(layout.mouthCenter.dy, lessThan(layout.size.height));
            combinations++;
          }
        }
      }
      expect(combinations, 90);
    },
  );
}
