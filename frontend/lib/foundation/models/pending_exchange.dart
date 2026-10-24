/// Immutable identity of one exchange, shared by both Core2 devices.
class PendingExchange {
  const PendingExchange({
    required this.transactionId,
    required this.myDeviceId,
    required this.peerDeviceId,
    required this.givenPetId,
    required this.gotPetId,
    required this.distanceMeters,
  });
  final String transactionId, myDeviceId, peerDeviceId, givenPetId, gotPetId;
  /// Distance measured by Core2 when it created the candidate.
  final double distanceMeters;
  static const maxDistanceMeters = 0.1;
  Map<String, dynamic> toMap() => {
    'transactionId': transactionId,
    'myDeviceId': myDeviceId,
    'peerDeviceId': peerDeviceId,
    'givenPetId': givenPetId,
    'gotPetId': gotPetId,
    'distanceMeters': distanceMeters,
  };
  factory PendingExchange.fromMap(Map<String, dynamic> map) {
    String field(String key) {
      final value = map[key];
      if (value is! String || value.isEmpty) {
        throw FormatException('交換情報の$keyが不正です');
      }
      return value;
    }

    final tx = field('transactionId');
    final mine = field('myDeviceId');
    final peer = field('peerDeviceId');
    if (!RegExp(r'^[0-9A-F]{16}$').hasMatch(tx) ||
        !RegExp(r'^[0-9A-F]{12}$').hasMatch(mine) ||
        !RegExp(r'^[0-9A-F]{12}$').hasMatch(peer) ||
        mine == peer) {
      throw const FormatException('交換IDまたは端末IDが不正です');
    }
    final given = field('givenPetId'), got = field('gotPetId');
    if (given == got) throw const FormatException('交換するペットIDが同一です');
    final distance = map['distanceMeters'];
    if (distance is! num ||
        !distance.isFinite ||
        distance <= 0 ||
        distance > maxDistanceMeters) {
      throw const FormatException('交換距離は0.1m以下である必要があります');
    }
    return PendingExchange(
      transactionId: tx,
      myDeviceId: mine,
      peerDeviceId: peer,
      givenPetId: given,
      gotPetId: got,
      distanceMeters: distance.toDouble(),
    );
  }
  bool sameAs(PendingExchange other) =>
      transactionId == other.transactionId &&
      myDeviceId == other.myDeviceId &&
      peerDeviceId == other.peerDeviceId &&
      givenPetId == other.givenPetId &&
      gotPetId == other.gotPetId;
}
