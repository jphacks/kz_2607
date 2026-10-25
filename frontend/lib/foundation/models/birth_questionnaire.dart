class BirthQuestion {
  const BirthQuestion(
    this.id,
    this.axis,
    this.axisLabel,
    this.title,
    this.options,
  );
  final String id, axis, axisLabel, title;
  final List<String> options;
}

/// Versioned contract: each option is ordered from the low to high end of its axis.
const birthQuestionnaireVersion = 'birth_v1_6q4';
const birthQuestions = <BirthQuestion>[
  BirthQuestion('q_activity', 'activity', '活発さ', '休みの日は、どう過ごしたい？', [
    '家でのんびり過ごしたい',
    '近所で少し気分転換したい',
    '外でいろいろ活動したい',
    '朝から外でたっぷり遊びたい',
  ]),
  BirthQuestion('q_nightowl', 'nightowl', '夜ふかし度', '自分の時間を楽しむなら、いつが好き？', [
    '朝早くがいちばん好き',
    'どちらかというと朝',
    'どちらかというと夜',
    '夜遅くがいちばん好き',
  ]),
  BirthQuestion('q_logical', 'logical', '理屈っぽさ', '何かを選ぶとき、どうやって決める？', [
    'ぱっと感じた直感で決める',
    '気持ちを大切にし、少し考える',
    '理由を比べ、最後は気持ちで決める',
    '理由や根拠をじっくり比べて決める',
  ]),
  BirthQuestion('q_friendly', 'friendly', '人懐っこさ', '初めて会う人とは、どう接したい？', [
    'まずは離れて様子を見たい',
    '話しかけられたら少し話したい',
    '慣れてきたら自分から話したい',
    '自分からどんどん話しかけたい',
  ]),
  BirthQuestion('q_curious', 'curious', '好奇心', '初めてのことに出会ったら、どうしたい？', [
    '慣れたことを楽しみたい',
    '評判を聞いてから考えたい',
    '少し調べて試してみたい',
    'まず自分で試してみたい',
  ]),
  BirthQuestion('q_talkative', 'talkative', 'おしゃべり度', '会話では、どんな役になることが多い？', [
    'じっくり聞くことが多い',
    '聞くことが多く、ときどき話す',
    '話すことが多く、相手の話も聞く',
    '自分からたくさん話す',
  ]),
];

class BirthAnswers {
  BirthAnswers(List<int> selected)
    : choices = List<int>.unmodifiable(selected) {
    if (choices.length != birthQuestions.length ||
        choices.any((v) => v < 0 || v > 3)) {
      throw const FormatException('6問すべてで1つずつ回答してください。');
    }
  }
  final List<int> choices;

  // v0 = 0.5 + 0.6 * (L - 0.5), L = optionIndex / 3.
  Map<String, double> get personalityAxes => {
    for (var i = 0; i < birthQuestions.length; i++)
      birthQuestions[i].axis: ((0.2 + choices[i] * 0.2) * 10).round() / 10,
  };

  /// API order differs from the order in which the questions are displayed.
  List<int> get apiAnswers {
    final byAxis = {
      for (var i = 0; i < birthQuestions.length; i++)
        birthQuestions[i].axis: choices[i],
    };
    return [
      for (final axis in [
        'activity',
        'friendly',
        'talkative',
        'logical',
        'curious',
        'nightowl',
      ])
        byAxis[axis]!,
    ];
  }

  /// AI-facing vocabulary; keep the legacy backend keys separate until API 1 is agreed.
  Map<String, double> get aiPersonalityAxes {
    final axes = personalityAxes;
    return {
      'active': axes['activity']!,
      'affection': axes['friendly']!,
      'talkative': axes['talkative']!,
      'logic': axes['logical']!,
      'curious': axes['curious']!,
      'night': axes['nightowl']!,
    };
  }

  String get birthTrait {
    final axes = aiPersonalityAxes;
    var best = axes.keys.first;
    for (final axis in axes.keys) {
      if (axes[axis]! > axes[best]!) best = axis;
    }
    return best;
  }

  Map<String, dynamic> toMap() => {
    'questionnaireVersion': birthQuestionnaireVersion,
    'answers': [
      for (var i = 0; i < birthQuestions.length; i++)
        {'questionId': birthQuestions[i].id, 'optionIndex': choices[i]},
    ],
    'personalityAxes': personalityAxes,
  };
}
