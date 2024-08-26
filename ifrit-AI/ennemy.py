import copy
import glob
import os
import re
import shutil
from math import floor

from command import Command
from gamedata import GameData

class Ennemy():
    DAT_FILE_SECTION_LIST = ['header', 'skeleton', 'model_geometry', 'model_animation', 'unknown_section4', 'unknown_section5', 'unknown_section6', 'info_stat',
                             'battle_script', 'sound', 'unknown_section10', 'texture']
    MAX_MONSTER_TXT_IN_BATTLE = 10
    MAX_MONSTER_SIZE_TXT_IN_BATTLE = 100

    def __init__(self, game_data):
        self.file_raw_data = bytearray()
        self.origin_file_name = ""
        self.origin_file_checksum = ""
        self.subsection_ai_offset = {'init_code': 0, 'ennemy_turn': 0, 'counter_attack': 0, 'death': 0, 'unknown': 0}
        self.header_data = copy.deepcopy(game_data.SECTION_HEADER_DICT)
        self.model_animation_data = copy.deepcopy(game_data.SECTION_MODEL_ANIM_DICT)
        self.info_stat_data = copy.deepcopy(game_data.SECTION_INFO_STAT_DICT)
        self.battle_script_data = copy.deepcopy(game_data.SECTION_BATTLE_SCRIPT_DICT)
        self.sound_data = bytes()  # Section 9
        self.sound_unknown_data = bytes()  # Section 10
        self.sound_texture_data = bytes()  # Section 11
        self.was_physical = False
        self.was_magic = False
        self.was_item = False
        self.was_gforce = False

    def __str__(self):
        return "Name: {} \nData:{}".format(self.info_stat_data['monster_name'],
                                           [self.header_data, self.model_animation_data, self.info_stat_data, self.battle_script_data])

    def load_file_data(self, file, game_data):
        with open(file, "rb") as f:
            while el := f.read(1):
                self.file_raw_data.extend(el)
        self.__analyze_header_section(game_data)
        self.origin_file_name = os.path.basename(file)
        # self.origin_file_checksum = get_checksum(file, algorithm='SHA256')

    def analyse_loaded_data(self, game_data, analyse_ia):
        """This is the main function. Here we have several cases.
        So first the based stat. As there is 4 stats for each in order to compute the final stat, they are stored in a list of size 4.
        For card, this is the ID for the different case: DROP, MOD, RARE_MOD
        There is common value of size 1, just raw value.
        % case with specific compute
        Elem and status have specific computation
        Devour is a set of ID for Low, medium, High
        Abilities
        """

        self.__analyze_animation_section(game_data)
        self.__analyze_info_stat(game_data)
        self.__analyze_battle_script_section(game_data, analyse_ia)
        self.__analyze_sound_section(game_data)
        self.__analyze_sound_unknown_section(game_data)
        self.__analyze_texture_section(game_data)

    def write_data_to_file(self, game_data, path, write_ia=True):
        print("Writing monster {}".format(self.info_stat_data["monster_name"]))
        # First copy original file
        full_dest_path = os.path.join(path, self.origin_file_name)
        # Then load file (python make it difficult to directly modify files)
        # Then modify loaded file
        section_position = 0
        for index_data, data in enumerate([self.model_animation_data, self.info_stat_data, self.battle_script_data]):
            if index_data == 0:
                section_position = 3
            if index_data == 1:
                section_position = 7
            if index_data == 2:
                section_position = 8
            for param_name, value in data.items():
                if param_name != 'battle_text' and 'ia_data' != param_name:  # Combat txt handled differently
                    property_elem = [x for ind, x in enumerate(
                        game_data.SECTION_INFO_STAT_LIST_DATA + game_data.SECTION_BATTLE_SCRIPT_LIST_DATA + game_data.SECTION_MODEL_ANIM_LIST_DATA) if
                                     x['name'] == param_name][0]
                if param_name in (game_data.stat_values + ['card', 'devour']):  # List of 1 byte value
                    value_to_set = bytes(value)
                elif param_name in ['med_lvl', 'high_lvl', 'extra_xp', 'xp', 'ap', 'nb_animation'] + game_data.BYTE_FLAG_LIST:
                    value_to_set = value.to_bytes(length=property_elem['size'], byteorder=property_elem['byteorder'])
                elif param_name in ['low_lvl_mag', 'med_lvl_mag', 'high_lvl_mag', 'low_lvl_mug', 'med_lvl_mug', 'high_lvl_mug', 'low_lvl_drop',
                                    'med_lvl_drop',
                                    'high_lvl_drop']:  # Case with 4 values linked to 4 IDs
                    value_to_set = []
                    for el2 in value:
                        value_to_set.append(el2['ID'])
                        value_to_set.append(el2['value'])
                    value_to_set = bytes(value_to_set)
                elif param_name in ['mug_rate', 'drop_rate']:  # Case with %
                    value_to_set = round((value * 255 / 100)).to_bytes()
                elif param_name in ['elem_def']:  # Case with elem
                    value_to_set = []
                    for i in range(len(value)):
                        value_to_set.append(floor((900 - value[i]) / 10))
                    value_to_set = bytes(value_to_set)
                elif param_name in ['status_def']:  # Case with elem
                    value_to_set = []
                    for i in range(len(value)):
                        value_to_set.append(value[i] + 100)
                    value_to_set = bytes(value_to_set)
                elif param_name in game_data.ABILITIES_HIGHNESS_ORDER:
                    value_to_set = bytearray()
                    for el2 in value:
                        value_to_set.extend(el2['type'].to_bytes())
                        value_to_set.extend(el2['animation'].to_bytes())
                        value_to_set.extend(el2['id'].to_bytes(2, property_elem['byteorder']))
                    value_to_set = bytes(value_to_set)
                elif param_name in ['monster_name']:
                    value_to_set = game_data.translate_str_to_hex(value)
                    # Completing the 0 after the name
                    for i in range(len(value_to_set), property_elem['size']):
                        value_to_set.append(0)
                elif param_name in ['renzokuken']:
                    value_to_set = bytearray()
                    for i in range(len(value)):
                        value_to_set.extend(value[i].to_bytes(2, game_data.SECTION_INFO_STAT_RENZOKUKEN['byteorder']))
                elif param_name == 'battle_text':  # Special case for text as the value change for each text
                    if value:
                        value_battle = bytearray()
                        for str_battle in value:
                            value_battle.extend(game_data.translate_str_to_hex(str_battle))
                            value_battle.extend([0])
                        self.file_raw_data[self.header_data['section_pos'][8] + self.battle_script_data['offset_text_sub']:
                                           self.header_data['section_pos'][8] + self.battle_script_data['offset_text_sub'] + len(value_battle)] = value_battle
                    continue  # Not setting the file_raw_data loop
                elif param_name == 'ia_data' and write_ia:
                    # Saving text
                    save_text = self.file_raw_data[self.header_data['section_pos'][8] + self.battle_script_data['offset_text_offset']:
                                                   self.header_data['section_pos'][9]]
                    list_offset = ['offset_init_code', 'offset_ennemy_turn', 'offset_counterattack', 'offset_death', 'offset_before_dying_or_hit']
                    offset_from_ai_subsection = self.battle_script_data['offset_init_code']
                    offset_from_current_section = 0
                    index_list_offset = 0
                    op_code_info_list = game_data.ai_data_json['op_code_info']
                    comparator_list = game_data.ai_data_json['list_comparator']
                    var_list = game_data.ai_data_json['list_var']
                    target_list = game_data.ai_data_json['list_target_char']

                    for command in value:
                        if command['id'] == -1:  # Separator
                            index_list_offset += 1
                            offset_from_ai_subsection += offset_from_current_section
                            if command['end']:
                                break
                            self.battle_script_data[list_offset[index_list_offset]] = offset_from_ai_subsection
                            offset_from_current_section = 0
                            continue
                        command_ref = [x for x in op_code_info_list if x['op_code'] == command['id']][0]
                        start_data = self.header_data['section_pos'][section_position] + self.battle_script_data[
                            'offset_ai_sub'] + offset_from_ai_subsection + offset_from_current_section
                        end_data = start_data + command_ref['size'] + 1  # +1 for taking into account the id we are writing
                        if command['id'] == 0x02:  # IF
                            comparator =comparator_list.index(command['comparator'])
                            jump = command['jump']
                            value_to_set = [command['id'], command['subject_id'], command['left_param'],
                                            comparator, command['right_param'], command['debug'], *jump]
                        elif command['id'] in [0x0E, 0x0F, 0x11, 0x12, 0x13, 0x15]:  # Modify var
                            if command['param'][-1] == '[global]':
                                if command['id'] in [0x0E, 0x0F, 0x11]:
                                    futur_command_id = 0x0F
                                elif command['id'] in [0x12, 0x13, 0x15]:
                                    futur_command_id = 0x13
                            elif command['param'][-1] == '[savemap]':
                                if command['id'] in [0x0E, 0x0F, 0x11]:
                                    futur_command_id = 0x11
                                elif command['id'] in [0x12, 0x13, 0x15]:
                                    futur_command_id = 0x15
                            else:
                                if command['id'] in [0x0E, 0x0F, 0x11]:
                                    futur_command_id = 0x0E
                                elif command['id'] in [0x12, 0x13, 0x15]:
                                    futur_command_id = 0x12
                            var_ref = [x for x in var_list if x['var_name'] == command['param'][0]]
                            if var_ref:
                                var_id = var_ref[0]['op_code']
                            else:
                                var_id = int(command['param'][0])
                            var_set = command['param'][1]
                            value_to_set = [futur_command_id, var_id, var_set]
                        elif command['id'] == 0x1A:  # LOCK PARAM TO REMOVE
                            value_to_set = [command['id'], command['param'][0]]
                        else:
                            value_to_set = [command['id'], *command['param']]
                        offset_from_current_section += command_ref['size'] + 1
                        self.file_raw_data[start_data:end_data] = bytes(value_to_set)

                    # Changing the section 9,10, 11 position and texts offset as we have moved everything a bit
                    # Writing new AI offset
                    for i, header in enumerate(game_data.SECTION_BATTLE_SCRIPT_AI_OFFSET_LIST_DATA):
                        self.file_raw_data[
                        self.header_data['section_pos'][8] + self.battle_script_data['offset_ai_sub'] + header['offset']:
                        self.header_data['section_pos'][8] + self.battle_script_data['offset_ai_sub'] + header['offset'] + header['size']] = (
                            self.battle_script_data[list_offset[i]]).to_bytes(
                            header['size'], header['byteorder'])

                    # Changing the text offset value and offset text offset value
                    length_offset_text_offset = self.battle_script_data['offset_text_sub'] - self.battle_script_data['offset_text_offset']
                    length_old_ia_section = self.battle_script_data['offset_text_offset'] - self.battle_script_data['offset_ai_sub']
                    self.battle_script_data['offset_text_offset'] = self.battle_script_data['offset_ai_sub'] + offset_from_ai_subsection
                    self.battle_script_data['offset_text_sub'] = self.battle_script_data['offset_text_offset'] + length_offset_text_offset
                    self.file_raw_data[self.header_data['section_pos'][8] + game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_OFFSET_SUB['offset']:
                                       self.header_data['section_pos'][8] + game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_OFFSET_SUB['offset'] +
                                       game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_OFFSET_SUB['size']] = self.battle_script_data[
                        'offset_text_offset'].to_bytes(game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_OFFSET_SUB['size'],
                                                       game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_OFFSET_SUB['byteorder'])
                    self.file_raw_data[self.header_data['section_pos'][8] + game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_SUB['offset']:
                                       self.header_data['section_pos'][8] + game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_SUB['offset'] +
                                       game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_SUB['size']] = self.battle_script_data['offset_text_sub'].to_bytes(
                        game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_SUB['size'], game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_SUB['byteorder'])

                    # Changing the file size
                    diff_ia_length = offset_from_ai_subsection - length_old_ia_section
                    futur_file_size = self.header_data['file_size'] + diff_ia_length
                    size_change = offset_from_ai_subsection - length_old_ia_section
                    if futur_file_size > self.header_data['file_size']:
                        self.file_raw_data.extend([0] * (futur_file_size - self.header_data['file_size']))
                    elif futur_file_size < self.header_data['file_size']:  # If the IA have been shorter, fill with 0
                        # Removing the last n byte
                        self.file_raw_data = self.file_raw_data[:-(self.header_data['file_size'] - futur_file_size) or None]
                    # Writing the new file size
                    self.header_data['file_size'] = futur_file_size
                    file_size_section_offset = 4 + self.header_data['nb_section'] * 4
                    self.file_raw_data[file_size_section_offset:file_size_section_offset + game_data.SECTION_HEADER_FILE_SIZE['size']] = (
                        self.header_data['file_size'].to_bytes(game_data.SECTION_HEADER_FILE_SIZE['size'], game_data.SECTION_HEADER_FILE_SIZE['byteorder']))

                    # Writing save text
                    self.file_raw_data[self.header_data['section_pos'][8] + self.battle_script_data['offset_text_offset']:
                                       self.header_data['section_pos'][8] + self.battle_script_data['offset_text_offset'] + len(save_text)] = save_text
                    # Writing section 9 10 11
                    new_section_9_offset = self.header_data['section_pos'][9] + size_change
                    data = self.sound_data + self.sound_unknown_data + self.texture_data
                    self.file_raw_data[new_section_9_offset:
                                       new_section_9_offset + len(self.sound_data) + len(self.sound_unknown_data) + len(self.texture_data)] = data
                    # Changing section 9 10 11 index:
                    for i in range(9, 12):
                        self.header_data['section_pos'][i] = self.header_data['section_pos'][i] + size_change
                        self.file_raw_data[game_data.SECTION_HEADER_SECTION_POSITION['offset'] + (i - 1) * game_data.SECTION_HEADER_SECTION_POSITION['size']:
                                           game_data.SECTION_HEADER_SECTION_POSITION['offset'] + game_data.SECTION_HEADER_SECTION_POSITION['size'] * (
                                               i)] = (self.header_data['section_pos'][i]).to_bytes(game_data.SECTION_HEADER_SECTION_POSITION['size'],
                                                                                                   game_data.SECTION_HEADER_SECTION_POSITION[
                                                                                                       'byteorder'])
                    continue  # Not setting the file_raw_data loop

                else:  # Data that we don't modify in the excel
                    continue
                if value_to_set:
                    self.file_raw_data[self.header_data['section_pos'][section_position] + property_elem['offset']:
                                       self.header_data['section_pos'][section_position] + property_elem['offset'] + property_elem['size']] = value_to_set

        # Write back on file
        with open(full_dest_path, "wb") as f:
            f.write(self.file_raw_data)

    def __get_int_value_from_info(self, data_info, section_number=0):
        return int.from_bytes(self.__get_raw_value_from_info(data_info, section_number), data_info['byteorder'])

    def __get_raw_value_from_info(self, data_info, section_number=0):
        if section_number == 0:
            section_offset = 0
        else:
            if section_number >= len(self.header_data['section_pos']):
                return bytearray(b'')
            section_offset = self.header_data['section_pos'][section_number]
        return self.file_raw_data[section_offset + data_info['offset']:section_offset + data_info['offset'] + data_info['size']]

    def __analyze_header_section(self, game_data):
        self.header_data['nb_section'] = self.__get_int_value_from_info(game_data.SECTION_HEADER_NB_SECTION)
        sect_position = [0]  # Adding to the list the header as a section 0
        for i in range(self.header_data['nb_section']):
            sect_position.append(
                int.from_bytes(self.file_raw_data[game_data.SECTION_HEADER_SECTION_POSITION['offset'] + i * game_data.SECTION_HEADER_SECTION_POSITION['size']:
                                                  game_data.SECTION_HEADER_SECTION_POSITION['offset'] +
                                                  game_data.SECTION_HEADER_SECTION_POSITION['size'] * (i + 1)],
                               game_data.SECTION_HEADER_SECTION_POSITION['byteorder']))
        self.header_data['section_pos'] = sect_position
        file_size_section_offset = 4 + self.header_data['nb_section'] * 4
        self.header_data['file_size'] = int.from_bytes(
            self.file_raw_data[file_size_section_offset:file_size_section_offset + game_data.SECTION_HEADER_FILE_SIZE['size']],
            game_data.SECTION_HEADER_FILE_SIZE['byteorder'])

    def __analyze_animation_section(self, game_data):  # Data loaded but not used or put in the excel for the moment
        self.model_animation_data['nb_animation'] = self.__get_int_value_from_info(game_data.SECTION_MODEL_ANIM_NB_MODEL, 3)

    def __analyze_sound_section(self, game_data):  # Data loaded but not used or put in the excel for the moment
        start_data = self.header_data['section_pos'][9]
        end_data = self.header_data['section_pos'][10]
        self.sound_data = self.file_raw_data[start_data:end_data]

    def __analyze_sound_unknown_section(self, game_data):  # Data loaded but not used or put in the excel for the moment
        start_data = self.header_data['section_pos'][10]
        end_data = self.header_data['section_pos'][11]
        self.sound_unknown_data = self.file_raw_data[start_data:end_data]

    def __analyze_texture_section(self, game_data):  # Data loaded but not used or put in the excel for the moment
        start_data = self.header_data['section_pos'][11]
        end_data = self.header_data['file_size']
        self.texture_data = self.file_raw_data[start_data:end_data]

    def __analyze_info_stat(self, game_data):
        SECTION_NUMBER = 7
        for el in game_data.SECTION_INFO_STAT_LIST_DATA:
            raw_data_selected = self.__get_raw_value_from_info(el, SECTION_NUMBER)
            data_size = len(raw_data_selected)
            if el['name'] in ['monster_name']:
                value = game_data.translate_hex_to_str(raw_data_selected)
            elif el['name'] in (game_data.stat_values + ['card', 'devour']):
                value = list(raw_data_selected)
            elif el['name'] in ['med_lvl', 'high_lvl', 'extra_xp', 'xp', 'ap', ]:
                value = int.from_bytes(raw_data_selected, byteorder=el['byteorder'])
            elif el['name'] in ['low_lvl_mag', 'med_lvl_mag', 'high_lvl_mag', 'low_lvl_mug', 'med_lvl_mug', 'high_lvl_mug', 'low_lvl_drop', 'med_lvl_drop',
                                'high_lvl_drop']:  # Case with 4 values linked to 4 IDs
                list_data = list(raw_data_selected)
                value = []
                for i in range(0, data_size - 1, 2):
                    value.append({'ID': list_data[i], 'value': list_data[i + 1]})
            elif el['name'] in ['mug_rate', 'drop_rate']:  # Case with %
                value = int.from_bytes(raw_data_selected) * 100 / 255
            elif el['name'] in ['elem_def']:  # Case with elem
                value = list(raw_data_selected)
                for i in range(data_size):
                    value[i] = 900 - value[i] * 10  # Give percentage
            elif el['name'] in game_data.ABILITIES_HIGHNESS_ORDER:
                list_data = list(raw_data_selected)
                value = []
                for i in range(0, data_size - 1, 4):
                    value.append({'type': list_data[i], 'animation': list_data[i + 1], 'id': int.from_bytes(list_data[i + 2:i + 4], el['byteorder'])})
            elif el['name'] in ['status_def']:  # Case with elem
                value = list(raw_data_selected)
                for i in range(data_size):
                    value[i] = value[i] - 100  # Give percentage, 155 means immune.
                if 'UNKNOWN_STAT' not in game_data.game_info_test.keys():
                    game_data.game_info_test['UNKNOWN_STAT'] = {}
            elif el['name'] in game_data.BYTE_FLAG_LIST:  # Flag in byte management
                byte_value = format((int.from_bytes(raw_data_selected)), '08b')[::-1]  # Reversing
                value = {}
                if el['name'] == 'byte_flag_0':
                    byte_list = game_data.SECTION_INFO_STAT_BYTE_FLAG_0_LIST_VALUE
                elif el['name'] == 'byte_flag_1':
                    byte_list = game_data.SECTION_INFO_STAT_BYTE_FLAG_1_LIST_VALUE
                elif el['name'] == 'byte_flag_2':
                    byte_list = game_data.SECTION_INFO_STAT_BYTE_FLAG_2_LIST_VALUE
                elif el['name'] == 'byte_flag_3':
                    byte_list = game_data.SECTION_INFO_STAT_BYTE_FLAG_3_LIST_VALUE
                else:
                    print("Unexpected byte flag {}".format(el['name']))
                    byte_list = game_data.SECTION_INFO_STAT_BYTE_FLAG_1_LIST_VALUE
                for index, bit_name in enumerate(byte_list):
                    value[bit_name] = +bool(int(byte_value[index]))
                    # For monster.txt purpose
                    if value[bit_name] == 1 and self.info_stat_data['monster_name'] != '\\n{NewPage}\\n{x0c00}/${x1000}{x0900}{x0c02}':
                        if bit_name not in game_data.game_info_test.keys():
                            game_data.game_info_test[bit_name] = []
                        # if self.info_stat_data['monster_name'] not in game_data.game_info_test.keys():
                        #    game_data.game_info_test[self.info_stat_data['monster_name']] = []
                        game_data.game_info_test[bit_name].append(self.info_stat_data['monster_name'] + " " + self.origin_file_name)
                        # game_data.game_info_test[self.info_stat_data['monster_name']].append({'bit_name':bit_name, 'bit_value':value[bit_name]})

                    # End monster.txt purpose
            elif el['name'] in 'renzokuken':
                value = []
                for i in range(0, el['size'], 2):  # List of 8 value of 2 bytes
                    value.append(int.from_bytes(raw_data_selected[i:i + 2], el['byteorder']))
            else:
                value = "ERROR UNEXPECTED VALUE"
                print("Unexpected name while analyzing info stat: {}".format(el['name']))

            self.info_stat_data[el['name']] = value

            # For monster.txt purpose
            if 'list_monster' not in game_data.game_info_test.keys():
                game_data.game_info_test['list_monster'] = []
            if self.info_stat_data['monster_name'] not in game_data.game_info_test['list_monster']:
                if '\\n{NewPage}\\n{x0c00}/${x1000}{x0900}{x0c02}' not in self.info_stat_data['monster_name']:
                    game_data.game_info_test['list_monster'].append(self.info_stat_data['monster_name'])

    def __analyze_battle_script_section(self, game_data, analyse_ia):
        SECTION_NUMBER = 8
        if len(self.header_data['section_pos']) <= SECTION_NUMBER:
            return
        section_offset = self.header_data['section_pos'][SECTION_NUMBER]

        # Reading header
        self.battle_script_data['battle_nb_sub'] = self.__get_int_value_from_info(game_data.SECTION_BATTLE_SCRIPT_HEADER_NB_SUB, SECTION_NUMBER)
        self.battle_script_data['offset_ai_sub'] = self.__get_int_value_from_info(game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_AI_SUB, SECTION_NUMBER)
        self.battle_script_data['offset_text_offset'] = self.__get_int_value_from_info(game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_OFFSET_SUB,
                                                                                       SECTION_NUMBER)
        self.battle_script_data['offset_text_sub'] = self.__get_int_value_from_info(game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_SUB, SECTION_NUMBER)

        # Reading text offset subsection
        nb_text = self.battle_script_data['offset_text_sub'] - self.battle_script_data['offset_text_offset']
        for i in range(0, nb_text, game_data.SECTION_BATTLE_SCRIPT_TEXT_OFFSET['size']):
            start_data = section_offset + self.battle_script_data['offset_text_offset'] + i
            end_data = start_data + game_data.SECTION_BATTLE_SCRIPT_TEXT_OFFSET['size']
            text_list_raw_data = self.file_raw_data[start_data:end_data]
            if i > 0 and text_list_raw_data == b'\x00\x00':  # Weird case where there is several pointer by the diff but several are 0 (which point to the same value)
                break
            self.battle_script_data['text_offset'].append(
                int.from_bytes(text_list_raw_data, byteorder=game_data.SECTION_BATTLE_SCRIPT_HEADER_OFFSET_TEXT_OFFSET_SUB['byteorder']))
        # Reading text sub-section
        for text_pointer in self.battle_script_data['text_offset']:  # Reading each text from the text offset
            combat_text_raw_data = bytearray()
            for i in range(self.MAX_MONSTER_SIZE_TXT_IN_BATTLE):  # Reading char by char to search for the 0
                char_index = section_offset + self.battle_script_data['offset_text_sub'] + text_pointer + i
                if char_index >= len(self.file_raw_data):  # Shouldn't happen, only on garbage data / self.header_data['file_size'] can be used
                    pass
                else:
                    raw_value = self.file_raw_data[char_index]
                    if raw_value != 0:
                        combat_text_raw_data.extend(int.to_bytes(raw_value))
                    else:
                        break
            if combat_text_raw_data:
                self.battle_script_data['battle_text'].append(game_data.translate_hex_to_str(combat_text_raw_data))
            else:
                self.battle_script_data['battle_text'] = []
        if analyse_ia:
            print("Analysing IA from loaded file")
            # Reading AI subsection

            ## Reading offset
            ai_offset = section_offset + self.battle_script_data['offset_ai_sub']
            for offset_param in game_data.SECTION_BATTLE_SCRIPT_AI_OFFSET_LIST_DATA:
                start_data = ai_offset + offset_param['offset']
                end_data = ai_offset + offset_param['offset'] + offset_param['size']
                self.battle_script_data[offset_param['name']] = int.from_bytes(self.file_raw_data[start_data:end_data], offset_param['byteorder'])

            start_data = ai_offset + self.battle_script_data['offset_init_code']
            end_data = ai_offset + self.battle_script_data['offset_ennemy_turn']
            init_code = list(self.file_raw_data[start_data:end_data])
            start_data = ai_offset + self.battle_script_data['offset_ennemy_turn']
            end_data = ai_offset + self.battle_script_data['offset_counterattack']
            ennemy_turn_code = list(self.file_raw_data[start_data:end_data])
            start_data = ai_offset + self.battle_script_data['offset_counterattack']
            end_data = ai_offset + self.battle_script_data['offset_death']
            counterattack_code = list(self.file_raw_data[start_data:end_data])
            start_data = ai_offset + self.battle_script_data['offset_death']
            end_data = ai_offset + self.battle_script_data['offset_before_dying_or_hit']
            death_code = list(self.file_raw_data[start_data:end_data])
            start_data = ai_offset + self.battle_script_data['offset_before_dying_or_hit']
            end_data = ai_offset + self.battle_script_data['offset_text_offset']
            before_dying_or_hit_code = list(self.file_raw_data[start_data:end_data])
            list_code = [init_code, ennemy_turn_code, counterattack_code, death_code, before_dying_or_hit_code]
            self.battle_script_data['ai_data'] = []
            for index, code in enumerate(list_code):
                index_read = 0
                list_result = []
                last_stop=False
                while index_read < len(code):
                    all_op_code_info = game_data.ai_data_json["op_code_info"]
                    op_code_ref = [x for x in all_op_code_info if x["op_code"] == code[index_read]]
                    if not op_code_ref and code[index_read] >= 0x40:
                        index_read += 1
                        continue
                    elif op_code_ref:  # >0x40 not used
                        op_code_ref = op_code_ref[0]
                        start_param = index_read + 1
                        end_param = index_read + 1 + op_code_ref['size']
                        command = Command(code[index_read], code[start_param:end_param], game_data, self.battle_script_data['battle_text'], self.info_stat_data['monster_name'])
                        list_result.append(command)
                        index_read += 1 + op_code_ref['size']
                    if code[index_read] == 0x00 and last_stop:
                        break
                    elif code[index_read] == 0x00:
                        last_stop = True
                    else:
                        last_stop = False
                self.battle_script_data['ai_data'].append(list_result)
            self.battle_script_data['ai_data'].append([])  # Adding a end section that is empty to mark the end of the all IA section

    def __remove_stop_end(self, list_result):
        id_remove = 0
        for i in range(len(list_result)):
            if list_result[i]['id'] == 0x00:  # STOP
                if i + 1 < len(list_result):
                    if list_result[i + 1]['id'] == 0x00:
                        id_remove = i + 1
                        break
        return list_result[:id_remove or None]


