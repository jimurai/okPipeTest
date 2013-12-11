import timeit
import struct
import ok

class PipeTest:
    def __init__(self):
        self.Check = False;
        self.u32BlockSize = 0;
        self.u32SegmentSize = 4*1024*1024;
        self.u32ThrottleIn = 0xffffffff;
        self.u32ThrottleOut = 0xffffffff;
        self.wordH = 0x0D0C0B0A
        self.wordL = 0x04030201
        return
    
    def InitializeDevice(self):
        print("---- Opal Kelly ---- PipeTest Application vX.Y ----\n");
        # Open the first device we find.
        self.xem = ok.okCFrontPanel()
        if (self.xem.NoError != self.xem.OpenBySerial("")):
            print("A device could not be opened.  Is one connected?")
            return(False)

        # Get some general information about the device.
        self.devInfo = ok.okTDeviceInfo()
        if (self.xem.NoError != self.xem.GetDeviceInfo(self.devInfo)):
            print("Unable to retrieve device information.")
            return(False)
        print("         Product: {}".format(self.devInfo.productName))
        print("Firmware version: {}.{}".format(self.devInfo.deviceMajorVersion, self.devInfo.deviceMinorVersion))
        print("   Serial Number: {}".format(self.devInfo.serialNumber))
        print("       Device ID: {}".format(self.devInfo.deviceID.split('\0')[0]))

        self.xem.LoadDefaultPLLConfiguration()

        # Download the configuration file.
        if self.devInfo.productName == 'XEM6002-LX9':
            config_file_name = '..\pipetest-xem6002.bit'
        else:
            config_file_name = ''
        if (self.xem.NoError != self.xem.ConfigureFPGA(config_file_name)):
            print("FPGA configuration failed.")
            return(False)

        # Check for FrontPanel support in the FPGA configuration.
        if (False == self.xem.IsFrontPanelEnabled()):
            print("FrontPanel support is not available.")
            return(False)
        print("FrontPanel support is available.")
        
        # Initialisation completed successfully
        return(True)

    def patternReset(self):
        self.wordH = 0x0D0B0C0A
        self.wordL = 0x04030201
        return

    def patternNext(self, pipe_width):
        bit = ((self.wordH>>31) ^ (self.wordH>>21) ^ (self.wordH>>1)) & 1
        self.wordH = ((self.wordH<<1) | bit) & 0xFFFFFFFF
        bit = ((self.wordL>>31) ^ (self.wordL>>21) ^ (self.wordL>>1)) & 1
        self.wordL = ((self.wordL<<1) | bit) & 0xFFFFFFFF
        return

    def generateData(self, pipe_width):
        # Array of zeros
        self.valid_data = bytearray(self.u32SegmentSize)
        byteCount = len(self.valid_data)
        self.patternReset()
        for i in range(0,byteCount,pipe_width/8):
            _wordL = struct.pack('>I',self.wordL)
            _wordH = struct.pack('>I',self.wordH)
            if pipe_width== 64:
                self.valid_data[i:4]    = _wordL
                self.valid_data[i+4:4]  = _wordH
            elif pipe_width== 32:
                self.valid_data[i:4]    = _wordL
            elif pipe_width== 16:
                self.valid_data[i:2]    = _wordL[0:2]
            elif pipe_width== 8:
                self.valid_data[i]      = _wordL[0]
            self.patternNext(pipe_width)
        return

    def Transfer(self, count, mode):
        ret = 0
        # Prep' for transfer
        self.xem.SetWireInValue(0x02, self.u32ThrottleIn)
        self.xem.SetWireInValue(0x01, self.u32ThrottleOut)
        # SET_THROTTLE=1 | MODE=LFSR | RESET=1
        self.xem.SetWireInValue(0x00, ((1<<5) | (1<<4) | (1<<2)))
        self.xem.UpdateWireIns()
        # SET_THROTTLE=0 | MODE=LFSR | RESET=0
        self.xem.SetWireInValue(0x00, ((0<<5) | (1<<4) | (0<<2)))
        self.xem.UpdateWireIns()
        
        # Start timing
        start = timeit.default_timer()
        
        # Data loop
        for i in xrange(count):
            _remaining = self.u32TransferSize
            while _remaining>0:
                _segsize = min(self.u32SegmentSize,_remaining)
                _remaining -= _segsize
                
                # If we're validating data, generate data per segment.
                if self.Check:
                    self.xem.SetWireInValue(0x00, ((0<<5) | (1<<4) | (1<<2)))
                    self.xem.UpdateWireIns();
                    self.xem.SetWireInValue(0x00, ((0<<5) | (1<<4) | (0<<2)))
                    self.xem.UpdateWireIns();
                    self.generateData(self.devInfo.pipeWidth)
        
                # Write/Read
                if mode=='Write':
                    self.valid_data = bytearray(self.u32SegmentSize)
                    if self.u32BlockSize == 0:
                        ret = self.xem.WriteToPipeIn(0x80, self.valid_data)
                    else:
                        ret = self.xem.WriteToBlockPipeIn(0x80, self.u32BlockSize, self.valid_data);
                else:
                    ret_data = bytearray(_segsize)
                    if self.u32BlockSize == 0:
                        ret = self.xem.ReadFromPipeOut(0xA0, ret_data)
                    else:
                        ret = self.xem.ReadFromBlockPipeOut(0xA0, self.u32BlockSize, ret_data);
                
                if ret < 0:
                    print("Pipe access failed: {}.".format(ret))
                if self.Check:
                    if mode!='Write':
                        _errors = 0
 
#                        for ch in ret_data:
                        for ch_in, ch_out in zip(ret_data, self.valid_data):
                            if ch_in != ch_out:
                                print(hex(ch_in), hex(ch_out))
                                _errors += 1
                                if _errors >100: break
                        if _errors > 0:
                            sys.exit()
                    else:
                        self.xem.UpdateWireOuts()
                        n = self.xem.GetWireOutValue(0x21)
                        if n>0:
                            print("ERROR: Data check failed. ({} errors)".format(n))
        
        return (ret,timeit.default_timer()-start)

    def BenchmarkWires(self):
        print "UpdateWireIns (1000 calls)\t",
        start = timeit.default_timer()
        for i in xrange(1000):
            self.xem.UpdateWireIns()
        elapsed = timeit.default_timer() - start
        print("Duration = {:.3f}s, {:.2f} calls/s".format(elapsed, 1000./elapsed))
        print "UpdateWireOuts (1000 calls)\t",
        start = timeit.default_timer()
        for i in xrange(1000):
            self.xem.UpdateWireOuts()
        elapsed = timeit.default_timer() - start
        print("Duration = {:.3f}s, {:.2f} calls/s".format(elapsed, 1000./elapsed))
        return

    def BenchmarkTriggers(self):
        print "ActivateTriggerIns (1000 calls)\t",
        start = timeit.default_timer()
        for i in xrange(1000):
            self.xem.ActivateTriggerIn(0x40, 0x01)
        elapsed = timeit.default_timer() - start
        print("Duration = {:.3f}s, {:.2f} calls/s".format(elapsed, 1000./elapsed))
        print "UpdateTriggerOuts (1000 calls)\t",
        start = timeit.default_timer()
        for i in xrange(1000):
            self.xem.UpdateTriggerOuts()
        elapsed = timeit.default_timer() - start
        print("Duration = {:.3f}s, {:.2f} calls/s".format(elapsed, 1000./elapsed))
        return

    def BenchmarkPipes(self):
        # BlockSize, SegmentSize,    TransferSize, Count
        test_matrix=\
        [[   0,      4*1024*1024,    64*1024*1024,     1 ], \
        [    0,      4*1024*1024,    32*1024*1024,     1 ], \
        [    0,      4*1024*1024,    16*1024*1024,     2 ], \
        [    0,      4*1024*1024,     8*1024*1024,     4 ], \
        [    0,      4*1024*1024,     4*1024*1024,     8 ], \
        [    0,      1*1024*1024,    32*1024*1024,     1 ], \
        [    0,         256*1024,    32*1024*1024,     1 ], \
        [    0,          64*1024,    16*1024*1024,     1 ], \
        [    0,          16*1024,     4*1024*1024,     1 ], \
        [    0,           4*1024,     1*1024*1024,     1 ], \
        [    0,           1*1024,     1*1024*1024,     1 ], \
        [ 1024,           1*1024,     1*1024*1024,     1 ], \
        [ 1024,      1*1024*1024,    32*1024*1024,     1 ], \
        [  900,      1*1024*1024,    32*1024*1024,     1 ], \
        [  800,      1*1024*1024,    32*1024*1024,     1 ], \
        [  700,      1*1024*1024,    32*1024*1024,     1 ], \
        [  600,      1*1024*1024,    32*1024*1024,     1 ], \
        [  512,      1*1024*1024,    32*1024*1024,     1 ], \
        [  500,      1*1024*1024,    32*1024*1024,     1 ], \
        [  400,      1*1024*1024,    16*1024*1024,     1 ], \
        [  300,      1*1024*1024,    16*1024*1024,     1 ], \
        [  256,      1*1024*1024,    16*1024*1024,     1 ], \
        [  200,      1*1024*1024,     8*1024*1024,     1 ], \
        [  128,      1*1024*1024,     8*1024*1024,     1 ], \
        [  100,      1*1024*1024,     8*1024*1024,     1 ]]
        
        for mode in ['Read', 'Write']:
            for row in test_matrix:
                self.u32BlockSize = row[0]
                self.u32SegmentSize = row[1]
                self.u32TransferSize = row[2]
                _count = row[3]
                if self.u32BlockSize != 0:
                    self.u32SegmentSize -= self.u32SegmentSize % self.u32BlockSize
                    self.u32TransferSize -= self.u32TransferSize % self.u32BlockSize
                print("{:5} BS: {:<10d}SS: {:<10d}TS: {:<10d}  ".format(mode,self.u32BlockSize,self.u32SegmentSize,self.u32TransferSize))
                (ret_val,elapsed) = self.Transfer(_count,mode)
                if ret_val < 0:
                    print("Error: {}".format(ret_val))
                print("Duration: {:.3f}s -- {:.2f}MB/s".format(elapsed/_count,_count*(self.u32TransferSize/2.**20)/elapsed))
                
        return
        
# Main code - currently benchtest only
if __name__ == '__main__':
    import sys
    print("------ Pipe Tester in Python ------")
    pt = PipeTest()
    if (False == pt.InitializeDevice()):
        sys.exit()   
    
    print("\nBenchmarking Wires")
    pt.BenchmarkWires()
    print("\nBenchmarking Triggers")
    pt.BenchmarkTriggers()
    print("\nBenchmarking Pipes")
    pt.BenchmarkPipes()