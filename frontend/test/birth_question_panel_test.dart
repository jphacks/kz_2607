import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/designsystem/birth_question_panel.dart';
import 'package:kz_2607/foundation/models/birth_questionnaire.dart';

void main() {
  testWidgets(
    'six questions require answers, allow edits, and submit once from review',
    (tester) async {
      final answers = List<int?>.filled(6, null);
      var submissions = 0;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: StatefulBuilder(
                builder: (context, update) => BirthQuestionPanel(
                  answers: answers,
                  busy: false,
                  locked: false,
                  onChanged: (question, choice) async {
                    update(() => answers[question] = choice);
                  },
                  onSubmit: () => submissions++,
                ),
              ),
            ),
          ),
        ),
      );
      expect(
        tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
        isNull,
      );
      for (var i = 0; i < 6; i++) {
        await tester.ensureVisible(find.text(birthQuestions[i].options[i % 4]));
        await tester.tap(find.text(birthQuestions[i].options[i % 4]));
        await tester.pump();
        final next = find.text(i == 5 ? '回答を確認する' : '次へ');
        await tester.ensureVisible(next);
        await tester.tap(next);
        await tester.pumpAndSettle();
      }
      expect(submissions, 0);
      await tester.ensureVisible(find.text('質問1を変更'));
      await tester.tap(find.text('質問1を変更'));
      await tester.pumpAndSettle();
      expect(find.text(birthQuestions.first.title), findsOneWidget);
      expect(answers, [0, 1, 2, 3, 0, 1]);
    },
  );

  testWidgets('pending save restores review and prevents changing answers', (
    tester,
  ) async {
    var submissions = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: BirthQuestionPanel(
              answers: List.filled(6, 2),
              busy: false,
              locked: true,
              onChanged: (_, _) async =>
                  fail('pending answers must remain locked'),
              onSubmit: () => submissions++,
            ),
          ),
        ),
      ),
    );
    expect(find.text('質問1を変更'), findsNothing);
    await tester.ensureVisible(find.text('同じ回答で保存を再試行'));
    await tester.tap(find.text('同じ回答で保存を再試行'));
    expect(submissions, 1);
  });
}
