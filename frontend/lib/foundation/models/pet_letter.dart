class PetLetter {
  const PetLetter({
    required this.letterId,
    required this.petId,
    required this.petName,
    required this.title,
    required this.body,
    required this.generation,
    required this.createdAt,
  });
  final String letterId, petId, title, body;
  final String? petName;
  final int generation;
  final DateTime createdAt;
  String get senderName =>
      petName?.trim().isNotEmpty == true ? petName! : '最初の子';

  factory PetLetter.fromMap(Map data) {
    for (final key in ['letterId', 'petId', 'title', 'body', 'createdAt']) {
      if (data[key] is! String || (data[key] as String).trim().isEmpty) {
        throw const FormatException('getLettersの応答が仕様と異なります');
      }
    }
    final at = DateTime.tryParse(data['createdAt'] as String);
    if (at == null ||
        data['generation'] is! int ||
        (data['generation'] as int) < 1 ||
        (data['petName'] != null && data['petName'] is! String)) {
      throw const FormatException('getLettersの応答が仕様と異なります');
    }
    return PetLetter(
      letterId: data['letterId'],
      petId: data['petId'],
      petName: data['petName'],
      title: data['title'],
      body: data['body'],
      generation: data['generation'],
      createdAt: at,
    );
  }
}

class LettersInbox {
  const LettersInbox({required this.firstPetId, required this.letters});
  final String? firstPetId;
  final List<PetLetter> letters;
}
