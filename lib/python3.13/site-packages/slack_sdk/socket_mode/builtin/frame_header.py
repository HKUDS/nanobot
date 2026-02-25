class FrameHeader:
    fin: int
    rsv1: int
    rsv2: int
    rsv3: int
    opcode: int
    masked: int
    length: int

    # Opcode
    # https://tools.ietf.org/html/rfc6455#section-5.2
    # Non-control frames
    # %x0 denotes a continuation frame
    OPCODE_CONTINUATION = 0x0
    # %x1 denotes a text frame
    OPCODE_TEXT = 0x1
    # %x2 denotes a binary frame
    OPCODE_BINARY = 0x2
    # %x3-7 are reserved for further non-control frames

    # Control frames
    # %x8 denotes a connection close
    OPCODE_CLOSE = 0x8
    # %x9 denotes a ping
    OPCODE_PING = 0x9
    # %xA denotes a pong
    OPCODE_PONG = 0xA

    # %xB-F are reserved for further control frames

    def __init__(
        self,
        opcode: int,
        fin: int = 1,
        rsv1: int = 0,
        rsv2: int = 0,
        rsv3: int = 0,
        masked: int = 0,
        length: int = 0,
    ):
        self.opcode = opcode
        self.fin = fin
        self.rsv1 = rsv1
        self.rsv2 = rsv2
        self.rsv3 = rsv3
        self.masked = masked
        self.length = length
