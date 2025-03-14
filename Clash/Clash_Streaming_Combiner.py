import os

# 设定文件夹路径
media_folder_path = '/Users/dockercs/Library/CloudStorage/OneDrive-个人/#007 MyTools/Network Proxy/Profiles/Rules/Clash/Provider/Media'

# 输出文件的名称
streamingCN_output_file = os.path.join(media_folder_path, 'StreamingCN.yaml')
streaming_output_file = os.path.join(media_folder_path, 'Streaming.yaml')

# 特定要合并的文件列表
all_files = os.listdir(media_folder_path)
streamingCN_files = {'Bilibili.yaml', 'IQ.yaml', 'IQIYI.yaml', 'Youku.yaml', 'Tencent Video.yaml', 'WeTV.yaml', 'MOO.yaml', 'Letv.yaml', 'Netease Music.yaml'}
streaming_files = list(set(all_files) - set(streamingCN_files) - set(['StreamingCN.yaml', 'Streaming.yaml']))

print(all_files, streamingCN_files, streaming_files)
print(len(all_files), len(streamingCN_files), len(streaming_files))

# 使用with语句确保文件正确关闭
with open(streamingCN_output_file, 'w', encoding='utf-8') as streamingCN_outfile, \
     open(streaming_output_file, 'w', encoding='utf-8') as streaming_outfile:

    # 先在每个输出文件写入"payload:"
    streamingCN_outfile.write('payload:\n')
    streaming_outfile.write('payload:\n')

    # 遍历文件夹中的所有文件
    for filename in os.listdir(media_folder_path):
        if filename.endswith('.yaml'):  # 确保处理的是.yaml文件
            file_path = os.path.join(media_folder_path, filename)
            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as infile:
                content = infile.readlines()  # 读取所有行
                if len(content) > 1:  # 如果文件有多于一行
                    # 去除第一行，并检查最后一行是否为空行
                    content_to_write = content[1:]
                    if '\n' in content[-1]:
                        # 如果最后一行已经是空行，则不额外添加
                        # content_to_write = content
                        content_to_write += ['\n']
                    else:
                        # 否则，在文件内容后添加一个空行
                        content_to_write += ['\n\n']

                    # 判断文件是否在特定文件列表中
                    if filename in streamingCN_files:
                        streamingCN_outfile.writelines(content_to_write)
                    elif filename in streaming_files:
                        streaming_outfile.writelines(content_to_write)

print("完成啦！两个.yaml文件已经根据你的要求合并完成，存储在同一个目录下。")
