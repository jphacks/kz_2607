import 'package:flutter/material.dart';
import '../foundation/app_colors.dart';

/// Code-drawn sample character until actual pet artwork is available.
class PetPortrait extends StatelessWidget {
  const PetPortrait({super.key, required this.name, this.size = 96});
  final String name;
  final double size;
  @override
  Widget build(BuildContext context) => Semantics(
    label: '$nameのキャラクター（表示サンプル）',
    image: true,
    child: ExcludeSemantics(
      child: Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: const BoxDecoration(
          color: AppColors.petBackground,
          shape: BoxShape.circle,
        ),
        child: CustomPaint(
          size: Size(size, size),
          painter: const _PetPainter(),
        ),
      ),
    ),
  );
}

class _PetPainter extends CustomPainter {
  const _PetPainter();
  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 140, size.height / 140);
    final paint = Paint()..isAntiAlias = true;
    canvas.drawOval(
      const Rect.fromLTWH(30, 109, 80, 10),
      paint..color = AppColors.primary.withValues(alpha: .10),
    );
    canvas.drawOval(
      const Rect.fromLTWH(42, 102, 20, 12),
      paint..color = AppColors.primary,
    );
    canvas.drawOval(const Rect.fromLTWH(79, 102, 20, 12), paint);
    final body = Path()
      ..moveTo(30, 82)
      ..cubicTo(29, 49, 45, 35, 70, 35)
      ..cubicTo(96, 35, 111, 52, 111, 83)
      ..cubicTo(111, 105, 97, 110, 70, 110)
      ..cubicTo(45, 110, 30, 104, 30, 82)
      ..close();
    canvas.drawPath(body, paint..color = AppColors.soft);
    canvas.drawPath(
      body,
      paint
        ..color = AppColors.primary
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
    paint.style = PaintingStyle.fill;
    final leaf = Path()
      ..moveTo(70, 36)
      ..cubicTo(52, 33, 52, 20, 53, 20)
      ..cubicTo(69, 20, 75, 27, 70, 36)
      ..close();
    canvas.drawPath(leaf, paint..color = AppColors.primary);
    canvas.drawOval(
      const Rect.fromLTWH(71, 24, 15, 10),
      paint..color = AppColors.gaugeTrack,
    );
    canvas.drawOval(
      const Rect.fromLTWH(42, 60, 57, 39),
      paint..color = const Color(0xFFFFFCF5),
    );
    canvas.drawCircle(const Offset(54, 76), 3.5, paint..color = AppColors.text);
    canvas.drawCircle(const Offset(86, 76), 3.5, paint);
    canvas.drawOval(
      const Rect.fromLTWH(44, 82, 12, 6),
      paint..color = const Color(0xFFF1C7AC),
    );
    canvas.drawOval(const Rect.fromLTWH(85, 82, 12, 6), paint);
    final smile = Path()
      ..moveTo(64, 83)
      ..quadraticBezierTo(70, 91, 76, 83);
    canvas.drawPath(
      smile,
      paint
        ..color = AppColors.text
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..strokeCap = StrokeCap.round,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _PetPainter oldDelegate) => false;
}
