import 'package:flutter/material.dart';
import '../foundation/app_colors.dart';
import '../foundation/models/birth_questionnaire.dart';
import 'app_card.dart';

/// Presentation only; answers and retry identity are owned by the birth flow.
class BirthQuestionPanel extends StatefulWidget {
  const BirthQuestionPanel({
    super.key,
    required this.answers,
    required this.onChanged,
    required this.onSubmit,
    required this.busy,
    required this.locked,
  });
  final List<int?> answers;
  final Future<void> Function(int question, int choice) onChanged;
  final VoidCallback onSubmit;
  final bool busy, locked;

  @override
  State<BirthQuestionPanel> createState() => _BirthQuestionPanelState();
}

class _BirthQuestionPanelState extends State<BirthQuestionPanel> {
  int _index = 0;
  bool _review = false;
  bool get _disabled => widget.busy || widget.locked;

  @override
  void initState() {
    super.initState();
    final unanswered = widget.answers.indexOf(null);
    _index = unanswered < 0 ? 0 : unanswered;
    _review = unanswered < 0 || widget.locked;
  }

  @override
  Widget build(BuildContext context) {
    final question = birthQuestions[_index];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Icon(Icons.egg_outlined, size: 64, color: AppColors.primary),
        const SizedBox(height: 16),
        Text(
          _review ? 'あなたのこと、教えてくれてありがとう' : 'あなたのことを少し教えてね',
          style: const TextStyle(
            fontSize: 22,
            height: 1.5,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          _review ? 'この回答から、この子の最初の性格が生まれます。' : '正解はありません。いちばん近いものを選んでね。',
          style: const TextStyle(color: AppColors.muted, height: 1.7),
        ),
        const SizedBox(height: 24),
        if (_review) ...[
          for (var i = 0; i < birthQuestions.length; i++)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: AppCard(
                padding: 18,
                radius: 20,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      birthQuestions[i].title,
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        height: 1.6,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      widget.answers[i] == null
                          ? '未回答'
                          : birthQuestions[i].options[widget.answers[i]!],
                      style: const TextStyle(
                        color: AppColors.primary,
                        height: 1.7,
                      ),
                    ),
                    if (!widget.locked)
                      TextButton(
                        onPressed: widget.busy
                            ? null
                            : () => setState(() {
                                _index = i;
                                _review = false;
                              }),
                        child: Text('質問${i + 1}を変更'),
                      ),
                  ],
                ),
              ),
            ),
          const Text(
            '送信後は回答を変更できません。',
            style: TextStyle(color: AppColors.muted, height: 1.7),
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: widget.busy || widget.answers.contains(null)
                ? null
                : widget.onSubmit,
            child: Text(widget.locked ? '同じ回答で保存を再試行' : 'この回答ではじめる'),
          ),
        ] else ...[
          Text(
            '質問 ${_index + 1} / ${birthQuestions.length}',
            style: const TextStyle(color: AppColors.primary),
          ),
          const SizedBox(height: 10),
          LinearProgressIndicator(
            value: (_index + 1) / birthQuestions.length,
            color: AppColors.primary,
            backgroundColor: AppColors.soft,
          ),
          const SizedBox(height: 24),
          Text(
            question.title,
            style: const TextStyle(
              fontSize: 20,
              height: 1.6,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 16),
          for (var choice = 0; choice < question.options.length; choice++)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: OutlinedButton(
                style: OutlinedButton.styleFrom(
                  alignment: Alignment.centerLeft,
                  padding: const EdgeInsets.all(18),
                  backgroundColor: widget.answers[_index] == choice
                      ? AppColors.soft
                      : AppColors.surface,
                  foregroundColor: AppColors.text,
                  side: BorderSide(
                    color: widget.answers[_index] == choice
                        ? AppColors.primary
                        : AppColors.gaugeTrack,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(18),
                  ),
                ),
                onPressed: _disabled
                    ? null
                    : () => widget.onChanged(_index, choice),
                child: Row(
                  children: [
                    Icon(
                      widget.answers[_index] == choice
                          ? Icons.radio_button_checked
                          : Icons.radio_button_off,
                      color: AppColors.primary,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        question.options[choice],
                        style: const TextStyle(height: 1.6),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _disabled || widget.answers[_index] == null
                ? null
                : () => setState(() {
                    if (_index == birthQuestions.length - 1) {
                      _review = true;
                    } else {
                      _index++;
                    }
                  }),
            child: Text(_index == birthQuestions.length - 1 ? '回答を確認する' : '次へ'),
          ),
          if (_index > 0)
            TextButton(
              onPressed: _disabled ? null : () => setState(() => _index--),
              child: const Text('前の質問へ'),
            ),
        ],
      ],
    );
  }
}
