"""
Example definition of a new protocol called "NewProtocol" (RFC -1).
New modules are placed into to appropriate layerXYZ-directory.
Last but not least: every protocol needs a testcase in tests/test_pypacker.py
"""
from pypacker import pypacker, triggerlist
from pypacker.pypacker_meta import FIELD_FLAG_AUTOUPDATE, FIELD_FLAG_IS_TYPEFIELD
from pypacker.layer3 import ip
from pypacker.structcbs import *


class NewProtocol(pypacker.Packet):
	"""New protocols are subclassing Packet"""

	"""
	The protocol header is basically defined by the static field
	"__hdr__" (see layer12/ethernet.Ethernet). See code documentation
	for classes "MetaPacket" and "Packet" in pypacker/pypacker.py for
	deeper information.
	"""
	__hdr__ = (
		# Simple constant fields (fixed format, not changing size),
		# marked as type field
		("type", "B", 0x12, FIELD_FLAG_IS_TYPEFIELD),
		("src", "4s", b"\xff" * 4),
		("dst", "4s", b"\xff" * 4),
		# Simple constant field, deactivatived
		# Switching between active/inactive should be avoided because of performance penalty :/
		("idk", "H", None),
		# Simple constant field, marked for auto update (see bin(...))
		("hlen", "H", 14, FIELD_FLAG_AUTOUPDATE),
		# Simple constant field
		("flags", "B", 0),
		# TriggerList field (variable length, can contain raw bytes, key/value-tuples and Packets)
		("options", None, triggerlist.TriggerList),
		# Dynamic field (bytestring format, *can* change size)
		# Field type should be avoided because of performance penalty :/
		("yolo", None, b"1234")
	)

	# Conveniant access should be enabled using properties eg using pypacker.get_property_xxx(...)
	src_s = pypacker.get_property_ip4("src")
	dst_s = pypacker.get_property_ip4("dst")
	# xxx_s = pypacker.get_property_mac("xxx")
	# xxx_s = pypacker.get_property_dnsname("xxx")

	# Setting/getting values smaller then 1 Byte should be enabled using properties (see layer3/ip.IP -> v, hl)
	def __get_flag_fluxcapacitor(self):
		return (self.flags & 0x80) >> 15

	def __set_flag_fluxcapacitor(self, value):
		value_shift = (value & 1) << 15
		self.flags = (self.flags & ~0x80) | value_shift

	flag_fluxcapacitor = property(__get_flag_fluxcapacitor, __set_flag_fluxcapacitor)

	@staticmethod
	def _parse_options(buf):
		"""Parse contents for TriggerList-field options"""
		ret = []
		off = 0

		while off < len(buf):
			ret.append(buf[off: off + 2])
			off += 2
		return ret

	def _dissect(self, buf):
		"""
		_dissect(...) must be overwritten if the header format can change
		from its original format. This is generally the case when
		- using TriggerLists
		- simple fields can get deactivated (see ethernet.Ethernet)
		- using dynamic fields

		In NewProtocol idk can get deactivated, options is a TriggerList
		and yolo is a dynamic field so _dissect(...) needs to be defined.
		"""
		# Header fields are not yet accessible in _dissect(...) so basic information
		# (type info, header length, bytes of dynamic content etc) has to be parsed manually.
		upper_layer_type = buf[0]
		total_header_length = unpack_H(buf[9: 11])[0]
		tl_bts = buf[12: total_header_length - 12]

		# self._init_triggerlist(...) should be called to initiate TriggerLists.
		# Otherwise the list will be empty.
		self._init_triggerlist("options", tl_bts, NewProtocol._parse_options)

		# self._init_handler(...) can be called to initiate the handler of the next
		# upper layer. Which handler to be called generally depends on the type information
		# found in the current layer (see layer12/ethernet.Ethernet -> type)
		self._init_handler(upper_layer_type, buf[total_header_length:])

	"""
	Handler can be registered by defining the static field dictionary
	__handler__ where the key is the value given to self._init_handler(...)
	when dissecting the value is used for creating the upper layer.
	Add the "FIELD_FLAG_IS_TYPEFIELD" to the corresponding type field in __hdr__.
	"""
	__handler__ = {0x66: ip.IP}  # just 1 handler, who needs more?

	def _update_fields(self):
		"""
		_update_fields(...) should be overwritten to update fields which depend on the state
		of the packet like lengths, checksums etc (see layer3/ip.IP -> len, sum)
		aka auto-update fields. The variable update_auto_fields indicates if any
		field should be updated in general, XXX_au_active in turn indicates
		if the field XXX should be updated (True) or not
		(see layer3/ip.IP.bin() -> len_au_active) in particular. XXX_au_active is
		available if the field has the flag "FIELD_FLAG_AUTOUPDATE" in __hdr__.
		"""
		if update_auto_fields and self._changed() and self.hlen_au_active:
			self.hlen = self.header_len

	def bin(self, update_auto_fields=True):
		"""
		bin(...)  should be overwritten to allow more complex assemblation (eg adding padding
		at the very end -> see ethernet.Ethernet)
		"""
		return pypacker.Packet.bin(self, update_auto_fields=update_auto_fields) + b"somepadding"

	def direction(self, other):
		"""
		direction(...) should be overwritten to be able to check directions to an other packet
		(see layer12/ethernet.Ethernet)
		"""
		direction = 0

		if self.src == other.src and self.dst == other.dst:
			direction |= pypacker.Packet.DIR_SAME
		if self.src == other.dst and self.dst == other.src:
			direction |= pypacker.Packet.DIR_REV

		if direction == 0:
			direction = pypacker.Packet.DIR_UNKNOWN
		return direction

	def reverse_address(self):
		"""
		reverse_address(...) should be overwritten to be able to reverse
		source/destination addresses (see ethernet.Ethernet)
		"""
		self.src, self.dst = self.dst, self.src

newproto_pkt = NewProtocol(type=0x1, src=b"12", dst=b"34", flags=0x56, options=[b"78"])
print("%r" % newproto_pkt)
