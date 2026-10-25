import 'dart:ui';

/// Coordinates are in the original animal PNG's pixels, not screen pixels.
/// Keeping each growth stage separate prevents face parts drifting as bodies grow.
class PetPartLayout {
  const PetPartLayout(
    this.size,
    this.leftEye,
    this.rightEye,
    this.mouthCenter,
    this.skin, {
    this.coverSize = const Size(42, 38),
  });
  final Size size, coverSize;
  final Offset leftEye, rightEye, mouthCenter;
  final Color skin;
  double get eyeSpacing => rightEye.dx - leftEye.dx;
  Offset get eyeCenter =>
      Offset((leftEye.dx + rightEye.dx) / 2, (leftEye.dy + rightEye.dy) / 2);

  static PetPartLayout forPet(String axis, String stage) =>
      layouts[axis]![stage]!;
  static const layouts = {
    'activity': {
      'baby': PetPartLayout(
        Size(280, 288),
        Offset(100, 106),
        Offset(178, 106),
        Offset(139, 151),
        Color(0xffe7a04a),
      ),
      'child': PetPartLayout(
        Size(294, 348),
        Offset(100, 106),
        Offset(178, 106),
        Offset(139, 151),
        Color(0xffe7a04a),
      ),
      'adult': PetPartLayout(
        Size(318, 408),
        Offset(110, 102),
        Offset(184, 102),
        Offset(147, 147),
        Color(0xffe7a04a),
      ),
    },
    'friendly': {
      'baby': PetPartLayout(
        Size(224, 288),
        Offset(70, 106),
        Offset(152, 106),
        Offset(111, 171),
        Color(0xffb98454),
      ),
      'child': PetPartLayout(
        Size(262, 348),
        Offset(90, 102),
        Offset(172, 102),
        Offset(131, 167),
        Color(0xffb98454),
      ),
      'adult': PetPartLayout(
        Size(292, 408),
        Offset(106, 98),
        Offset(188, 98),
        Offset(147, 161),
        Color(0xffb98454),
      ),
    },
    'talkative': {
      'baby': PetPartLayout(
        Size(218, 288),
        Offset(79, 101),
        Offset(141, 101),
        Offset(110, 137),
        Color(0xffffe15a),
        coverSize: Size(24, 34),
      ),
      'child': PetPartLayout(
        Size(222, 348),
        Offset(81, 85),
        Offset(143, 85),
        Offset(112, 121),
        Color(0xffffe15a),
        coverSize: Size(24, 34),
      ),
      'adult': PetPartLayout(
        Size(214, 408),
        Offset(79, 83),
        Offset(139, 83),
        Offset(109, 119),
        Color(0xffffe15a),
        coverSize: Size(24, 34),
      ),
    },
    'logical': {
      'baby': PetPartLayout(
        Size(264, 288),
        Offset(94, 118),
        Offset(170, 118),
        Offset(132, 153),
        Color(0xfff4deb0),
        coverSize: Size(44, 30),
      ),
      'child': PetPartLayout(
        Size(290, 348),
        Offset(102, 124),
        Offset(188, 124),
        Offset(145, 163),
        Color(0xfff4deb0),
        coverSize: Size(44, 30),
      ),
      'adult': PetPartLayout(
        Size(296, 408),
        Offset(106, 142),
        Offset(192, 142),
        Offset(149, 181),
        Color(0xfff4deb0),
        coverSize: Size(44, 30),
      ),
    },
    'curious': {
      'baby': PetPartLayout(
        Size(236, 288),
        Offset(65, 87),
        Offset(129, 87),
        Offset(97, 119),
        Color(0xffd8b47a),
        coverSize: Size(42, 42),
      ),
      'child': PetPartLayout(
        Size(242, 348),
        Offset(65, 83),
        Offset(125, 83),
        Offset(95, 115),
        Color(0xffd8b47a),
        coverSize: Size(40, 40),
      ),
      'adult': PetPartLayout(
        Size(244, 408),
        Offset(61, 81),
        Offset(119, 81),
        Offset(90, 112),
        Color(0xffd8b47a),
        coverSize: Size(38, 38),
      ),
    },
    'nightowl': {
      'baby': PetPartLayout(
        Size(256, 288),
        Offset(94, 126),
        Offset(162, 126),
        Offset(128, 163),
        Color(0xfff6e3c8),
        coverSize: Size(44, 30),
      ),
      'child': PetPartLayout(
        Size(268, 348),
        Offset(100, 132),
        Offset(168, 132),
        Offset(134, 171),
        Color(0xfff6e3c8),
        coverSize: Size(44, 30),
      ),
      'adult': PetPartLayout(
        Size(308, 408),
        Offset(122, 134),
        Offset(186, 134),
        Offset(154, 175),
        Color(0xfff6e3c8),
        coverSize: Size(44, 30),
      ),
    },
  };

  // Source eye pairs have different transparent margins and eye spacing.
  static const eyeSizes = {
    'activity': Size(218, 98),
    'friendly': Size(232, 95),
    'talkative': Size(184, 102),
    'logical': Size(236, 74),
    'curious': Size(190, 88),
    'nightowl': Size(228, 72),
  };
  static const eyeSeparations = {
    'activity': 120.0,
    'friendly': 120.0,
    'talkative': 120.0,
    'logical': 120.0,
    'curious': 120.0,
    'nightowl': 120.0,
  };
  // The eye line is not always the vertical midpoint (e.g. lashes / sparkles).
  static const eyeLine = {
    'activity': 49.0,
    'friendly': 38.0,
    'talkative': 51.0,
    'logical': 35.0,
    'curious': 55.0,
    'nightowl': 30.0,
  };
  static const mouthSizes = {
    'activity': Size(258, 163),
    'friendly': Size(274, 97),
    'talkative': Size(147, 179),
    'logical': Size(221, 99),
    'curious': Size(125, 130),
    'nightowl': Size(221, 98),
  };
}
