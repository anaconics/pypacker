# $Id: dpkt.py 43 2007-08-02 22:42:59Z jon.oberheide $

"""Simple packet creation and parsing."""

import copy, itertools, socket, struct
import logging

logging.basicConfig(format='%(levelname)s: %(message)s')
#logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.DEBUG)
logger = logging.getLogger("pypacker")
logger.setLevel(logging.INFO)


class Error(Exception): pass
class UnpackError(Error): pass
class NeedData(UnpackError): pass
class PackError(Error): pass


class MetaPacket(type):
	"""This Metaclass is an easier way of setting attributes than adding
	fields via "self.xyz = somevalue" in __init__. This is done
	by reading name / format / default out of __hdr__ in every subclass.
	This configuration is set one time when loading the module (not
	at instatiation). A default of None means: skip this field.
	Actual values are retrieved using "obj.field" notation.
	More complex fields like TCP-options need their own parsing
	in sub-classes.

	TODO: check if header-switches are needed in different cases eg ABC -> ACB
	"""
	def __new__(cls, clsname, clsbases, clsdict):
		#print("MetaPacket __new__")
		t = type.__new__(cls, clsname, clsbases, clsdict)
		# get header-infos from subclass
		st = getattr(t, '__hdr__', None)
		if st is not None:
			# XXX - __slots__ only created in __new__()
			clsdict['__slots__'] = [ x[0] for x in st ] + [ 'data' ]
			t = type.__new__(cls, clsname, clsbases, clsdict)
			# set fields for name/format/default
			t.__hdr_fields__ = [ x[0] for x in st ]
#			t.__hdr_fmt__ = getattr(t, '__byte_order__', '>') + \
#				# skip format if default value is None
#				''.join([ x[1] if x[2] not None else pass for x in st ])
			t.__hdr_fmt__ = [ getattr(t, '__byte_order__', '>')] + \
				# skip format if default value is None
				[ x[1] for x in st if x[2] not None ]
			t.__hdr_fmtstr__ = "".join(t.__hdr_fmt__)	# full formatstring for convenience
			t.__hdr_defaults__ = dict(list(zip(
				t.__hdr_fields__, [ x[2] for x in st ])))

			t.__hdr_len__ = struct.calcsize(t.__hdr_fmt__)
		return t

class Packet(metaclass=MetaPacket):
	"""Base packet class, with metaclass magic to generate members from
	self.__hdr__. This class can be instatiated via:

		Packet(byte_array)
		Packet(key1=val1, key2=val2, ...)

	Requirements:
		- Auto-decoding of static headers via given format-patterns
		- Enable/disable specific header fields (optional fields)
		- Add dynamic header fields
		- Access of fields via "layer1.key" notation
		- Ooncatination via "layer1/layer2"
			Note: layer1 could save wrong information about layer2
			like type information in ethernet. This won't be checked.
		- Ability to check for relation to other layers via "is_related()"
		- Generic callback for rare cases eg where upper layer needs
			to know about lower ones (like TCP->IP for checksum calculation)

	Every packet got an optional header and an optional body.
	Body-data can be raw byte-array or a packet itself
	which stores the data. The following schema illustrates the structure of a Packet:

	Packet structure
	================
	[headerfield1]
	[headerfield2]
	[headerfield13]
	...
	[Packet
		[Packet
		... 
			[Packet: raw data]
	]]

	New Protocols are added by subclassing Packet and defining fields via "__hdr__"
	as a list of (name, structfmt, default) tuples.	__byte_order__ can be set to
	override the default ('>').
	Extending classes should have their own "unpack"-method, which itself
	should call pypacker.Packet.unpack(self, buf) to decode the full header.
	By calling unpack of the subclass first, we can handle optional (set default
	header value, eg VLAN in ethernet) or dynamic (update via "_add_hdrfield",
	eg TCP-options)	header-fields. The full header MUST be defined using __hdr__
	or _add_hdrfield() after finishing "unpack" in the extending class.

	Call-flow:
	==========
		pypacker(__init__) -auto calls-> sub(unpack): manipulate if needed (add optional parts etc)
			-manually call-> pypacker(parse all static + optional parts) -> ...
		without overwritten unpack in sub:
		pypacker(__init__) -auto calls-> pypacker(parse static parts)


	All data up to the transport layer should be auto decoded like
		e = Ethernet(raw_data) # get tcp via e.ip.tcp, will be None if not present
	Higher layers should be accessed via
		http = Http(tcp.data)
	and don't know lower layers. (Exceptionally a callback can be used for this purpose).
	The following methods must be called in pypacker if overwritten:
		unpack()
		__setattribute__()
	
	Example::

	>>> class Foo(Packet):
	...	  __hdr__ = (('foo', 'I', 1), ('bar', 'H', 2), ('baz', '4s', 'quux'))
	...
	>>> foo = Foo(bar=3)
	>>> foo
	Foo(bar=3)
	>>> str(foo)
	'\x00\x00\x00\x01\x00\x03quux'
	>>> foo.bar
	3
	>>> foo.baz
	'quux'
	>>> foo.foo = 7
	>>> foo.baz = 'whee'
	>>> foo
	Foo(baz='whee', foo=7, bar=3)
	>>> Foo(b'hello, world!')
	Foo(baz=' wor', foo=1751477356L, bar=28460, data='ld!')
	"""

	def __init__(self, *args, **kwargs):
		print("subclass??? %s" % self.__hdr_fields__)
		"""Packet constructor with ([buf], [field=val,...]) prototype.

		Arguments:

		buf -- optional packet buffer to unpack as bytes

		Optional keyword arguments correspond to members to set
		(matching fields in self.__hdr__, or 'data').
		"""
		print("Packet __init__")
		# body as raw byte-array
		self.data = ''
		# name of the attribute which holds the object which represents the body
		self.bodytypename = None
		# callback for other layers
		self.callback = None
		# track changes to header and data. Layers like TCP need this eg for checksum-recalculation
		# TODO: to be implemented
		# set to "True" on __set_attribute(), set to False on "__str__()" or "bin()"
		self.packet_changed = False

		if args:
			# buffer given: use it to set attributes
			print("Packet args: %s" % args)
			try:
				# this is called on the extended class if present
				self.unpack(args[0])
			except struct.error:
				if len(args[0]) < self.__hdr_len__:
					raise NeedData
				raise UnpackError('invalid %s: %r' % (self.__class__.__name__, args[0]))
		else:
			print("Packet no args")
			# set default attributes
			for k in self.__hdr_fields__:
				object.__setattr__(self, k, copy.copy(self.__hdr_defaults__[k]))
			# additional parameters given, those can overwrite the class-based attributes
			for k, v in kwargs.items():
				object.__setattr__(self, k, v)

	def __len__(self):
		"""return length in bytes."""
		return self.__hdr_len__ + len(self.data)

	def __setattribute__(self, k, v):
		"""Set value of an attribute a via "a.k=v". Track changes to fields
		for later packing."""
		oldval = self.object.__getattribute__(self, k)
		object.__setattribute__(self, k, v)

		# changes to data not allowed if there is a handler for that
		if self.bodytypename is not None and k == "data":
			raise Error("attempt to change data on layer with bodyhandler")

		# TODO: reset on output
		object.__set_attr(self, "packet_changed", True)
		# changes which affect format
		if v is None and oldval is not None or
			v is not None and oldval is None:
			__update_fmtstr()

	def __div__(self, v):
                """Handle concatination of protocols like "ethernet/ip/tcp."""
		if type(v) == bytes:
			raise Error("Can not concat bytes")
                self._set_bodyhandler(v)

	def callback_impl(self, id):
		"""Generic callback. The calling class must know if/how this callback
		is implemented for this class and which id is needed
		(eg. id "calc_sum" for IP checksum calculation in TCP used of pseudo-header)"""
		pass

	def is_related(self, next):
		"""Every layers can check the given layer (of the next packet) is related
		to itself and continues this on the next upper layer if there is a relation.
		This stops if there is no relation or the body data is not a Packet.
		The extending class should call this on overwriting. This will return
		True if the body (self or next) is just raw bytes."""
		# raw bytes as body, assume it's related
		if self.bodytypename is None or next.bodytypename is None
			return True
		else:
			# body is a Packet and this layer is related, we must go deeper on Packets
			body_p_this = getattr(self, self.bodytypename)
			body_p_next = getattr(next, next.bodytypename)

			return body_p_this.is_related(body_p_next)

	def _add_headerfield(self, name, format, value):
		"""Add a new (dynamic) header field in contrast to the static ones.
		Optional header fields are not stored in __hdr__ but can be accessed
		via "obj.attrname" after all.
		"""
		# Update internal header data. This won't break anything because
		# all field-informations are allready initialized via metaclass.
		self.__hdr_fields__.append(name)
		self.__hdr_fmt__ += format
		self.__hdr_defaults__[name] = value
		object.__setattr__(self, name, value)

		# fields with value None won't change format string
		if value is not None:
			__update_fmtstr()

	def __update_fmtstr(self):
		"""Update header format string using fields whose value are not None.
		take __hdr_fields__ and not __hdr__: optional headers could have been added"""
		st = self.__getattr__(self, '__hdr_fields__', None)
		__hdr_fmtstr__ = self.getattr(t, '__byte_order__', '>') + \
			''.join([ self.__hdr_fmt__[idx] for idx,f in enumerate(st)
				# skip format if value is None
				if self.__getattr__(self, f, None) is not None])
		__hdr_len__ = struct.calcsize(t.__hdr_fmtstr__)
		# avoid circular dependencies
		object.__setattr__(self, "__hdr_fmtstr__", __hdr_fmtstr__)
		object.__setattr__(self, "__hdr_len__", __hdr_len__)
		
	def _set_bodyhandler(self, obj):
		"""Add handler to decode the actual data using the given obj
		and make it accessible via layername.addedtype like ethernet.ip.
		The following assumption is true for the first three layers:
			layer1(layer1_layer2_data) == layer1(layer1_data)/layer2(layer2_data)
		"""
		try:
			callbackimpl_tmp = None
			# remove previous handler
			if self.bodytypename is not None:
				callbackimpl_tmp =  getattr(self, self.bodytypename).callback
				delattr(self, self.bodytypename)
			self.bodytypename = type_instance.__class__.__name__.lower()
			# associate ip, arp etc with handler-instance to call "ether.ip", "ip.tcp" etc
			obj.callback = callbackimpl_tmp
			object.__setattr__(self, self.bodytypename, obj)
                except (KeyError, dpkt.UnpackError):
                        print("dpkt _set_bodyhandler except")

	def __repr__(self):
		"""
		Unique represention of this packet.
		"""
		l = [ '%s=%r' % (k, getattr(self, k))
			for k in self.__hdr_defaults__
				if getattr(self, k) != self.__hdr_defaults__[k] ]
		if self.data:
			l.append('data=%r' % self.data)
		return '%s(%s)' % (self.__class__.__name__, ', '.join(l))

	def __str__(self):
		"""Return header + body as hex-string."""
		if type(self.data) == bytes:
			# header as hex + data as hex
			return self.pack_hdr() + byte2hex(self.data)
		else:
			# header as hex + call str implementation of higher layer
			return self.pack_hdr() + str(self.data)

	def bin(self):
		"""Convert header + body to a byte-array."""
		# full header bytes, skip fields with value None
		header_bin = [ getattr(self, k) for k in self.__hdr_fields__
				if k is not None]
		# body is raw data, return without change
		if self.bodytypename is None:
			return header_bin + self.data
		else
			# We got a complex type (eg. ip) set via _set_bodyhandler, call bin() itself
			return header_bin + getattr(self, self.bodytypename).bin()

	def pack_hdr(self):
		"""Return header as hex-represenation like \x00\x01\x02.
		Headers ar added in order of appearance in __hdr_fmt__. Header with
		value None will be skipped."""
		try:
			return struct.pack(self.__hdr_fmtstr__,
				# skip fields with value None
				*[ getattr(self, k) for k in self.__hdr_fields__
					if k not None])
		except struct.error:
			vals = []

			for k in self.__hdr_fields__:
				v = getattr(self, k)
				# None means: skip field, eg. VLAN in ethernet
				if v is None:
					continue
				if isinstance(v, tuple):
					vals.extend(v)
				else:
					vals.append(v)
				format.append()

		try: # EAFP: this is likely to work
			return struct.pack(self.__hdr_fmtstr__, *vals)
		except struct.error as e:
			raise PackError(str(e))

	def pack(self):
		"""Pack/export packed header + data as hexstring."""
		return str(self)

	def unpack(self, buf):
		"""Unpack/import a full layer using bytes in buf and set all headers
		and data appropriate. This can be called multiple times, eg to retrieve data to
		parse dynamic headers afterwards (Note: avoid this for performance reasons)."""
		print("Packet unpack")

		for k, v in zip(self.__hdr_fields__,
			struct.unpack(self.__hdr_fmtstr__,
				 buf[:self.__hdr_len__])):
			object.__setattr__(self, k, v)
		self.data = buf[self.__hdr_len__:]

# XXX - ''.join([(len(`chr(x)`)==3) and chr(x) or '.' for x in range(256)])
__vis_filter = """................................ !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[.]^_`abcdefghijklmnopqrstuvwxyz{|}~................................................................................................................................."""

def byte2hex(buf):
	"""
	Convert a bytestring to a hex-represenation:
	b'1234' -> '\x31\x32\x33\x34'
	"""
	return "\\x"+"\\x".join( [ "%02X" % x for x in buf ] )

def hexdump(buf, length=16):
	"""Return a hexdump output string of the given buffer."""
	n = 0
	res = []
	while buf:
		line, buf = buf[:length], buf[length:]
		hexa = ' '.join(['%02x' % ord(x) for x in line])
		line = line.translate(__vis_filter)
		res.append('  %04d:	 %-*s %s' % (n, length * 3, hexa, line))
		n += length
	return '\n'.join(res)

try:
	import dnet
	def in_cksum_add(s, buf):
		return dnet.ip_cksum_add(buf, s)
	def in_cksum_done(s):
		return socket.ntohs(dnet.ip_cksum_carry(s))
except ImportError:
	import array
	# TODO: use raw bytes
	def in_cksum_add(s, buf):
		n = len(buf)
		cnt = (n / 2) * 2
		a = array.array('H', buf[:cnt])
		if cnt != n:
			#a.append(struct.unpack('H', buf[-1] + '\x00')[0])
			a.append(buf[-1] + '\x00')
		return s + sum(a)
	def in_cksum_done(s):
		s = (s >> 16) + (s & 0xffff)
		s += (s >> 16)
		return socket.ntohs(~s & 0xffff)

def in_cksum(buf):
	"""Return computed Internet checksum."""
	return in_cksum_done(in_cksum_add(0, buf))
