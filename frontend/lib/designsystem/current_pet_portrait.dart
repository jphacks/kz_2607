import 'package:flutter/material.dart';
import '../foundation/app_colors.dart';
import '../foundation/models/pet_appearance.dart';
import '../foundation/models/pet_parts.dart';
import 'pet_part_layout.dart';

/// PNG layers share the animal's pixel coordinate system, then scale as one unit.
class CurrentPetPortrait extends StatelessWidget {
  const CurrentPetPortrait({
    super.key,
    required this.name,
    required this.appearance,
    this.size = 130,
  });
  final String name;
  final PetAppearance? appearance;
  final double size;

  Widget _missing() => SizedBox(
    width: size,
    height: size,
    child: const Center(
      child: Icon(Icons.pets_outlined, size: 52, color: AppColors.primary),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final appearance = this.appearance;
    if (appearance == null) return _missing();
    final parts = PetParts(appearance);
    final layout = PetPartLayout.forPet(appearance.primary, appearance.stage);
    final eyeSource = PetPartLayout.eyeSizes[appearance.secondary]!;
    final eyeScale =
        layout.eyeSpacing / PetPartLayout.eyeSeparations[appearance.secondary]!;
    final eyeSize = Size(
      eyeSource.width * eyeScale,
      eyeSource.height * eyeScale,
    );
    final mouthSource = PetPartLayout.mouthSizes[parts.mouthAxis]!;
    final mouthWidth =
        layout.eyeSpacing *
        switch (parts.mouthAxis) {
          'talkative' => .29,
          'curious' => .25,
          _ => .62,
        };
    final mouthSize = Size(
      mouthWidth,
      mouthWidth * mouthSource.height / mouthSource.width,
    );
    Widget image(String asset, double width, double height) => Image.asset(
      asset,
      width: width,
      height: height,
      fit: BoxFit.fill,
      filterQuality: FilterQuality.medium,
      errorBuilder: (_, _, _) => const SizedBox.shrink(),
    );
    return Semantics(
      image: true,
      label: '$nameのキャラクター',
      child: ExcludeSemantics(
        child: SizedBox(
          width: size,
          height: size,
          child: FittedBox(
            fit: BoxFit.contain,
            child: SizedBox(
              width: layout.size.width,
              height: layout.size.height,
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  image(
                    parts.animalAsset,
                    layout.size.width,
                    layout.size.height,
                  ),
                  Positioned.fill(
                    child: CustomPaint(
                      painter: _OriginalEyesCover(layout, appearance.primary),
                    ),
                  ),
                  Positioned(
                    left: layout.eyeCenter.dx - eyeSize.width / 2,
                    top:
                        layout.eyeCenter.dy -
                        PetPartLayout.eyeLine[appearance.secondary]! * eyeScale,
                    child: image(
                      parts.eyesAsset,
                      eyeSize.width,
                      eyeSize.height,
                    ),
                  ),
                  Positioned(
                    left: layout.mouthCenter.dx - mouthSize.width / 2,
                    top: layout.mouthCenter.dy - mouthSize.height / 2,
                    child: image(
                      parts.mouthAsset,
                      mouthSize.width,
                      mouthSize.height,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The supplied body PNGs already contain eyes. Cover them without changing the
/// original files so that secondary-axis eyes do not produce two sets of eyes.
class _OriginalEyesCover extends CustomPainter {
  const _OriginalEyesCover(this.layout, this.axis);
  final PetPartLayout layout;
  final String axis;
  @override
  void paint(Canvas canvas, Size size) {
    for (final eye in [layout.leftEye, layout.rightEye]) {
      final rect = Rect.fromCenter(
        center: eye,
        width: layout.coverSize.width,
        height: layout.coverSize.height,
      );
      canvas.save();
      canvas.clipRect(rect);
      canvas.drawRect(rect, Paint()..color = layout.skin);
      if (axis == 'activity') {
        // Restore the cream muzzle where it crosses the lower edge of the eyes.
        canvas.drawOval(
          Rect.fromCenter(
            center: Offset(layout.eyeCenter.dx, layout.mouthCenter.dy),
            width: layout.eyeSpacing * 2.18,
            height: 94,
          ),
          Paint()..color = const Color(0xfffff5e4),
        );
      }
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(covariant _OriginalEyesCover oldDelegate) =>
      oldDelegate.layout != layout || oldDelegate.axis != axis;
}
