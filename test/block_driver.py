import os
import shutil
import sys
import unittest
from hashlib import sha3_256
from typing import List, Tuple

sys.path.append('../src/')

from grpcbigbuffer import buffer_pb2
from grpcbigbuffer.block_builder import build_multiblock, get_position_length
from grpcbigbuffer.client import Enviroment

import math


def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def write_filesystem_to_directory(filesystem, directory):
    """
    Write the file system of the Filesystem object to the specified directory.
    """
    if not os.path.exists(directory):
        os.makedirs(directory)
    else:
        os.system('rm -rf __generated_filesystem__/*')
    for item_branch in filesystem.branch:
        item_name = item_branch.name
        item = item_branch.WhichOneof('item')
        item_path = os.path.join(directory, item_name)
        if item == 'file':
            block = buffer_pb2.Buffer.Block()
            block.ParseFromString(item_branch.file)
            block_id: str = os.path.join(Enviroment.block_dir, block.hashes[0].value.hex())
            shutil.copyfile(block_id, item_path)
        elif item == 'link':
            pass
            # os.symlink(item_branch.link, item_path)
        elif item == 'filesystem':
            write_filesystem_to_directory(item_branch.filesystem, item_path)


class TestGetVarintValue(unittest.TestCase):
    def test_simple_varint(self):
        # Test a simple varint with a single byte
        buffer = b"\x7F"
        value = get_position_length(0, buffer)
        self.assertEqual(value, 127)

    def test_multi_byte_varint(self):
        # Test a varint with multiple bytes
        buffer = b"\xC0\x03"
        value = get_position_length(0, buffer)
        self.assertEqual(value, 448)

    def test_max_varint(self):
        # Test the maximum varint value (2**64 - 1)
        buffer = b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x01"
        value = get_position_length(0, buffer)
        self.assertEqual(value, 18446744073709551615)

    def test_varint_at_position(self):
        # Test a varint at a non-zero position in the buffer
        buffer = b"\x00\x00\xC0\x03"
        value = get_position_length(2, buffer)
        self.assertEqual(value, 448)


class TestWBPFileGeneration(unittest.TestCase):
    def test_object_generate_wbp_file(self):
        # Assuming that the build_multiblock_directory() function works correctly (tests/block_builder.py is OK)
        from grpcbigbuffer.test_pb2 import Test

        def generate_block(with_hash=True):
            block1 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block1").digest()
            block1.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block1").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block1").hexdigest(), 'wb') as file:
                    file.write(
                        b''.join([b'block1' for i in range(100)])
                    )

            block2 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block2").digest()
            block2.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block2").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block2").hexdigest(), 'wb') as file:
                    file.write(
                        b''.join([b'block2' for i in range(100)])
                    )

            block3 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block3").digest()
            block3.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block3").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block3").hexdigest(), 'wb') as file:
                    file.write(
                        b''.join([b'block3' for i in range(100)])
                    )

            a = Test()
            a.t1 = b''.join([b'bt1' for i in range(1)])
            a.t2 = block1.SerializeToString()

            b = Test()
            b.t1 = block2.SerializeToString()
            b.t2 = b''.join([b'bt2' for i in range(100)])
            b.t3.CopyFrom(a)

            c = Test()
            c.t1 = b''.join([b'ct1' for i in range(100)])
            c.t2 = block3.SerializeToString()

            _object = Test()
            _object.t1 = b''.join([b'mc1' for i in range(100)])
            _object.t2 = b''.join([b'mc2' for i in range(100)])
            _object.t4.append(b)
            _object.t4.append(c)
            _object.t5 = b'final'
            return _object

        object_id, cache_dir = build_multiblock(
            pf_object_with_block_pointers=generate_block(),
            blocks=[
                sha3_256(b"block1").digest(),
                sha3_256(b"block2").digest(),
                sha3_256(b"block3").digest()
            ]
        )

        # Test generate_wbp_file
        from grpcbigbuffer.block_driver import generate_wbp_file
        os.system('rm ' + cache_dir + '/wbp.bin')
        generate_wbp_file(cache_dir)

        generated = Test()
        with open(cache_dir + '/wbp.bin', 'rb') as f:
            generated.ParseFromString(
                f.read()
            )

        # Now the assertEqual is performed between generated and the _object without specifying the hash type.

        self.assertEqual(generate_block(with_hash=False), generated)

    def test_filesystem_generate_wbp_file(self):
        # Assuming that the build_multiblock_directory() function works correctly (tests/block_builder.py is OK)
        from grpcbigbuffer.test_pb2 import Filesystem, ItemBranch

        def generate_block(with_hash=True) -> Filesystem:
            block1 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block1").digest()
            block1.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block1").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block1").hexdigest(), 'wb') as file:
                    file.write(
                        b''.join([b'block1' for i in range(100)])
                    )

            block2 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block2").digest()
            block2.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block2").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block2").hexdigest(), 'wb') as file:
                    file.write(
                        b''.join([b'block2' for i in range(100)])
                    )

            block3 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block3").digest()
            block3.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block3").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block3").hexdigest(), 'wb') as file:
                    file.write(
                        b''.join([b'block3' for i in range(100)])
                    )

            item1 = ItemBranch()
            item1.name = ''.join(['item1' for i in range(1)])
            item1.file = block1.SerializeToString()

            item2 = ItemBranch()
            item2.name = ''.join(['item2' for i in range(5)])
            item2.file = block2.SerializeToString()

            item3 = ItemBranch()
            item3.name = ''.join(['item3' for i in range(10)])
            item3.file = block3.SerializeToString()

            item4 = ItemBranch()
            item4.name = "item4"
            item4.file = block3.SerializeToString()

            item5 = ItemBranch()
            item5.name = "item5"
            item5.filesystem.branch.append(item3)
            item5.filesystem.branch.append(item4)

            filesystem: Filesystem = Filesystem()
            filesystem.branch.append(item1)
            filesystem.branch.append(item3)
            filesystem.branch.append(item4)
            filesystem.branch.append(item5)
            return filesystem

        filesystem, blocks = generate_block(), [
                sha3_256(b"block1").digest(),
                sha3_256(b"block2").digest(),
                sha3_256(b"block3").digest()
            ]

        print('\n build multiblock')
        print('\n\n\nBUILD MULTIBLOCK ', filesystem.ByteSize(), '\ncount blocks -> ', len(blocks), '\nblocks -> ',
              [len(b) for b in blocks], '\n\n')

        write_filesystem_to_directory(filesystem, '__generated_filesystem__')

        object_id, cache_dir = build_multiblock(
            pf_object_with_block_pointers=filesystem,
            blocks=blocks
        )

        print('\n generate wbp file')
        # Test generate_wbp_file
        from grpcbigbuffer.block_driver import generate_wbp_file
        os.system('rm ' + cache_dir + '/wbp.bin')
        generate_wbp_file(cache_dir)

        print('\n Read generated wbp file.')
        generated = Filesystem()
        with open(cache_dir + '/wbp.bin', 'rb') as f:
            generated.ParseFromString(
                f.read()
            )

        # Ahora se realiza el assertEqual entre generated y el _object sin especificar el tipo de hash.

        self.assertEqual(generate_block(with_hash=False), generated)

    def test_complex_filesystem_generate_wbp_file(self):
        # Assuming that the build_multiblock_directory() function works correctly (tests/block_builder.py is OK)
        from grpcbigbuffer.test_pb2 import Filesystem, ItemBranch

        def generate_block(with_hash=True) -> Tuple[Filesystem, List[bytes]]:

            # BLOQUES

            block_lengths: int = pow(10, 7)
            block_factor_length = 3


            block1 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block1").digest()
            block1.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block1").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block1").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block1' for i in range(block_lengths)])
                        )
                    file.write(b'end')


            block2 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block2").digest()
            block2.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block2").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block2").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block2' for i in range(block_lengths)])
                        )
                    file.write(b'end')


            block3 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block3").digest()
            block3.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block3").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block3").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block3' for i in range(block_lengths)])
                        )
                    file.write(b'end')


            block6 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block6").digest()
            block6.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block6").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block6").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block6' for i in range(block_lengths)])
                        )
                    file.write(b'end')


            block7 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block7").digest()
            block7.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block7").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block7").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block7' for i in range(block_lengths)])
                        )
                    file.write(b'end')


            block8 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block8").digest()
            block8.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block8").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block8").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block8' for i in range(block_lengths)])
                        )
                    file.write(b'end')   


            block12 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block12").digest()
            block12.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block12").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block12").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block12' for i in range(block_lengths)])
                        )
                    file.write(b'end')   


            block13 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block13").digest()
            block13.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block13").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block13").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block13' for i in range(block_lengths)])
                        )
                    file.write(b'end')   


            block14 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block14").digest()
            block14.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block14").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block14").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block14' for i in range(block_lengths)])
                        )
                    file.write(b'end')


            block15 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block15").digest()
            block15.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block15").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block15").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block15' for i in range(block_lengths)])
                        )
                    file.write(b'end')                    


            block16 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block16").digest()
            block16.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block16").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block16").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block16' for i in range(block_lengths)])
                        )
                    file.write(b'end')  


            block17 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block17").digest()
            block17.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block17").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block17").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block17' for i in range(block_lengths)])
                        )
                    file.write(b'end')  



            block18 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block18").digest()
            block18.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block18").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block18").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block18' for i in range(block_lengths)])
                        )
                    file.write(b'end')  


            block19 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block19").digest()
            block19.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block19").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block19").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block19' for i in range(block_lengths)])
                        )
                    file.write(b'end') 


            block20 = buffer_pb2.Buffer.Block()
            h = buffer_pb2.Buffer.Block.Hash()
            if with_hash: h.type = Enviroment.hash_type
            h.value = sha3_256(b"block20").digest()
            block20.hashes.append(h)

            if not os.path.isfile(Enviroment.block_dir + sha3_256(b"block20").hexdigest()):
                with open(Enviroment.block_dir + sha3_256(b"block20").hexdigest(), 'wb') as file:
                    for c in range(block_factor_length):
                        file.write(
                            b''.join([b'block20' for i in range(block_lengths)])
                        )
                    file.write(b'end') 


            # ITEMS

            item1 = ItemBranch()
            item1.name = ''.join(['item1' for i in range(1)]) #item-name
            item1.file = block1.SerializeToString()

            item2 = ItemBranch()
            item2.name = ''.join(['item2' for i in range(1)]) #item-name
            item2.file = block2.SerializeToString()

            item3 = ItemBranch()
            item3.name = ''.join(['item3' for i in range(1)]) #item-name
            item3.file = block3.SerializeToString()

            item4 = ItemBranch()
            item4.name = ''.join(['item4' for i in range(1)]) #item-name
            item4.filesystem.branch.append(item1)
            item4.filesystem.branch.append(item3)

            item5 = ItemBranch()
            item5.name = ''.join(['item5' for i in range(1)]) #item-name
            item5.filesystem.branch.append(item2)
            item5.filesystem.branch.append(item4)

            item6 = ItemBranch()
            item6.name = ''.join(['item6' for i in range(1)]) #item-name
            item6.file = block6.SerializeToString()

            item7 = ItemBranch()
            item7.name = ''.join(['item7' for i in range(1)]) #item-name
            item7.file = block7.SerializeToString()

            item8 = ItemBranch()
            item8.name = ''.join(['item8' for i in range(1)]) #item-name
            item8.file = block8.SerializeToString()

            item9 = ItemBranch()
            item9.name = ''.join(['item9' for i in range(1)]) #item-name
            item9.filesystem.branch.append(item6)
            item9.filesystem.branch.append(item7)

            item10 = ItemBranch()
            item10.name = ''.join(['item10' for i in range(1)]) #item-name
            item10.filesystem.branch.append(item5)
            item10.filesystem.branch.append(item9)

            
            item11 = ItemBranch()
            item11.name = ''.join(['item11' for i in range(1)]) #item-name
            item11.filesystem.branch.append(item10)
            item11.filesystem.branch.append(item8)
            

            item12 = ItemBranch()
            item12.name = ''.join(['item12' for i in range(1)]) #item-name
            item12.file = block12.SerializeToString()


            item13 = ItemBranch()
            item13.name = ''.join(['item13' for i in range(1)]) #item-name
            item13.file = block13.SerializeToString()


            item14 = ItemBranch()
            item14.name = ''.join(['item14' for i in range(1)]) #item-name
            item14.file = block14.SerializeToString()

            
            item15 = ItemBranch()
            item15.name = ''.join(['item15' for i in range(1)]) #item-name
            item15.file = block15.SerializeToString()

            item16 = ItemBranch()
            item16.name = ''.join(['item16' for i in range(1)]) #item-name
            item16.file = block16.SerializeToString()

            item17 = ItemBranch()
            item17.name = ''.join(['item17' for i in range(1)]) #item-name
            item17.file = block17.SerializeToString()


            item18 = ItemBranch()
            item18.name = ''.join(['item18' for i in range(1)]) #item-name
            item18.file = block18.SerializeToString()


            item19 = ItemBranch()
            item19.name = ''.join(['item19' for i in range(1)]) #item-name
            item19.file = block19.SerializeToString()


            item20 = ItemBranch()
            item20.name = ''.join(['item20' for i in range(1)]) #item-name
            item20.file = block1.SerializeToString()


            item21 = ItemBranch()
            item21.name = ''.join(['item21' for i in range(1)]) #item-name
            item21.filesystem.branch.append(item12)
            item21.filesystem.branch.append(item13)
            item21.filesystem.branch.append(item14)
            item21.filesystem.branch.append(item15)


            item22 = ItemBranch()
            item22.name = ''.join(['item22' for i in range(1)]) #item-name
            item22.filesystem.branch.append(item16)
            item22.filesystem.branch.append(item17)


            item23 = ItemBranch()
            item23.name = ''.join(['item23' for i in range(1)]) #item-name
            item23.filesystem.branch.append(item18)
            item23.filesystem.branch.append(item19)
            item23.filesystem.branch.append(item21)


            item24 = ItemBranch()
            item24.name = ''.join(['item24' for i in range(1)]) #item-name
            item24.filesystem.branch.append(item22)
            item24.filesystem.branch.append(item20)
            item24.filesystem.branch.append(item23)


            _filesystem: Filesystem = Filesystem()
            _filesystem.branch.append(item11)
            _filesystem.branch.append(item24)

            _blocks = [
                sha3_256(b"block1").digest(),
                sha3_256(b"block2").digest(),
                sha3_256(b"block3").digest(),
                sha3_256(b"block6").digest(),
                sha3_256(b"block7").digest(),
                sha3_256(b"block8").digest(),
                sha3_256(b"block12").digest(),
                sha3_256(b"block13").digest(),
                sha3_256(b"block14").digest(),
                sha3_256(b"block15").digest(),
                sha3_256(b"block16").digest(),
                sha3_256(b"block17").digest(),
                sha3_256(b"block18").digest(),
                sha3_256(b"block19").digest(),
                sha3_256(b"block20").digest(),
            ]

            byte_size = _filesystem.ByteSize() + sum([os.path.getsize(b) for b in os.scandir('__block__')])
            print('\nIndividual sizes -< ', _filesystem.ByteSize(), [os.path.getsize(b) for b in os.scandir('__block__')])
            print('Size -> ', byte_size, convert_size(byte_size))

            return _filesystem, _blocks

        filesystem, blocks = generate_block()

        print('\n build multiblock')
        print('\n\n\nBUILD MULTIBLOCK ', filesystem.ByteSize(), '\ncount blocks -> ', len(blocks), '\nblocks -> ', [len(b) for b in blocks], '\n\n')

        write_filesystem_to_directory(filesystem, '__generated_filesystem__')

        object_id, cache_dir = build_multiblock(
            pf_object_with_block_pointers=filesystem,
            blocks=blocks
        )

        print('\n generate wbp file')
        # Test generate_wbp_file
        from grpcbigbuffer.block_driver import generate_wbp_file
        os.system('rm ' + cache_dir + '/wbp.bin')
        generate_wbp_file(cache_dir)

        print('\n Read generated wbp file.')
        generated = Filesystem()
        with open(cache_dir + '/wbp.bin', 'rb') as f:
            generated.ParseFromString(
                f.read()
            )

        # Ahora se realiza el assertEqual entre generated y el _object sin especificar el tipo de hash.
        self.assertEqual(generate_block(with_hash=False)[0], generated)


if __name__ == "__main__":
    os.makedirs("__cache__", exist_ok=True)
    os.makedirs("__block__", exist_ok=True)
    os.makedirs("__generated_filesystem__", exist_ok=True)
    os.system('rm -rf __cache__/*')
    os.system('rm -rf __block__/*')
    os.system("rm -rf __generated_filesystem__/*")
    TestWBPFileGeneration().test_complex_filesystem_generate_wbp_file()


"""
Individual sizes -<  1347 [180000003, 210000003, 210000003, 210000003, 180000003, 180000003, 180000003, 210000003, 210000003, 180000003, 210000003, 210000003, 210000003, 180000003, 210000003]
Size ->  2970001392 2.77 GB

 build multiblock



BUILD MULTIBLOCK  1347 
count blocks ->  15 
blocks ->  [32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32] 



 generate wbp file

Blocks: {'a9478c2003b2357fed7a40c13c44ee0501de09792796963b9377a374de0eed55': [[1, 15, 21, 35, 41, 54, 60, 72]], 'f3eaaf62a95cd5b89291803dbd0278b443afad7e3cdcb968aba9397904a458c8': [[1, 15, 21, 35, 41, 54, 180000080, 180000093, 180000099, 180000111], [1080000218, 1080000232, 1500000300, 1500000313]], 'ba42e833104b6b641ff06470299b2100992b57f49ed29ce17ad84f8881db501a': [[1, 15, 21, 35, 41, 54, 180000080, 180000093, 360000119, 360000131]], '56c0f514442f87cf2e1dc6634fa8c3c71f57dc337fb9a89f6f19898f9934af77': [[1, 15, 21, 35, 540000139, 540000152, 540000158, 540000170]], '68f46e56ee64bf926904ef8c9bdc7b4b560c292f3e388b4c695d130569118e8b': [[1, 15, 21, 35, 540000139, 540000152, 720000178, 720000190]], 'ae09269c8eeb3bab022965c48ccc2085c0a96e921208bd659a2fc7232c3fb2fa': [[1, 15, 900000198, 900000210]], '49e3a4699287e728b0140300400e33ac4b7f5f3e00a52c39b3c29a7a578ca188': [[1080000218, 1080000232, 1080000238, 1080000252, 1080000258, 1080000271]], '4ef5f89409efe3cb745d1b0bdfe053f35255cfa93e087164c41f6cb7070434e1': [[1080000218, 1080000232, 1080000238, 1080000252, 1290000279, 1290000292]], '43557fff91ab23bbf2cd51e4d703d396b960d46b1214f7ffb06af9a883ce8bcb': [[1080000218, 1080000232, 1680000321, 1680000335, 1680000341, 1680000354]], '4a4f250a5eca9567b59e3f4a730efac4e947c90771092d74a3d06416d9c3a967': [[1080000218, 1080000232, 1680000321, 1680000335, 1890000362, 1890000375]], '5a2aaa9ea66d1392effd29a081fa1e941618de2ba182acbc575c74c7a6cf718d': [[1080000218, 1080000232, 1680000321, 1680000335, 2100000383, 2100000397, 2100000403, 2100000416]], '05ed7404c9e17ee9b254d868b6e329929f5be191e24c17fc3c9311f61a72711f': [[1080000218, 1080000232, 1680000321, 1680000335, 2100000383, 2100000397, 2310000424, 2310000437]], '9003c0bc6a71d40fbe0c9e2f2c267e6ffb49cf19f0996b94cf16ca561a3cb5dc': [[1080000218, 1080000232, 1680000321, 1680000335, 2100000383, 2100000397, 2520000445, 2520000458]], '832c01446bc6a438a6870481b3a83bffd8270ce7915ac5520bc1ad607b24a354': [[1080000218, 1080000232, 1680000321, 1680000335, 2100000383, 2100000397, 2730000466, 2730000479]]}

 Read generated wbp file.

Individual sizes -<  831 [180000003, 210000003, 210000003, 210000003, 180000003, 180000003, 180000003, 210000003, 210000003, 180000003, 210000003, 210000003, 210000003, 180000003, 210000003]
Size ->  2970000876 2.77 GB
"""