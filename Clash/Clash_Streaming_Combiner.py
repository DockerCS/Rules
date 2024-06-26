import os

# 设定文件夹路径
folder_path = 'D:/OneDrive/#007 MyTools/Network Proxy/Profiles/Rules/Clash/Provider/Media'

# 特定要合并的文件列表
special_files = {'Bilibili.yaml', 'IQ.yaml', 'IQIYI.yaml', 'Youku.yaml', 'Tencent Video.yaml', 'WeTV.yaml', 'MOO.yaml', 'Letv.yaml', 'Netease Music.yaml'}

# 输出文件的名称
special_output_file = os.path.join(folder_path, 'StreamingCN.yaml')
general_output_file = os.path.join(folder_path, 'Streaming.yaml')

# 使用with语句确保文件正确关闭
with open(special_output_file, 'w', encoding='utf-8') as special_outfile, \
     open(general_output_file, 'w', encoding='utf-8') as general_outfile:

    # 先在每个输出文件写入"payload:"
    special_outfile.write('payload:\n')
    general_outfile.write('payload:\n')

    # 遍历文件夹中的所有文件
    for filename in os.listdir(folder_path):
        if filename.endswith('.yaml'):  # 确保处理的是.yaml文件
            file_path = os.path.join(folder_path, filename)
            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as infile:
                content = infile.readlines()  # 读取所有行
                if len(content) > 1:  # 如果文件有多于一行
                    # 去除第一行，并检查最后一行是否为空行
                    content_to_write = content[1:]
                    if content_to_write[-1].strip() == '':
                        # 如果最后一行已经是空行，则不额外添加
                        content_to_write = content_to_write
                    else:
                        # 否则，在文件内容后添加一个空行
                        content_to_write += ['\n']

                    # 判断文件是否在特定文件列表中
                    if filename in special_files:
                        special_outfile.writelines(content_to_write)
                    else:
                        general_outfile.writelines(content_to_write)

print("完成啦！两个.yaml文件已经根据你的要求合并完成，存储在同一个目录下。")
