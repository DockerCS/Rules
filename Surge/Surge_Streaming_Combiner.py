import os

# 设定文件夹路径
folder_path = 'D:/OneDrive/#007 MyTools/Network Proxy/Profiles/Rules/Surge/Provider/Media'

# 特定要合并的文件列表
special_files = {'Bilibili.list', 'IQIYI.list', 'Youku.list', 'Tencent Video.list', 'Letv.list', 'Netease Music.list'}

# 输出文件的名称
special_output_file = os.path.join(folder_path, 'StreamingCN.list')
general_output_file = os.path.join(folder_path, 'Streaming.list')

# 使用with语句确保文件正确关闭
with open(special_output_file, 'w', encoding='utf-8') as special_outfile, \
     open(general_output_file, 'w', encoding='utf-8') as general_outfile:

    # 遍历文件夹中的所有文件
    for filename in os.listdir(folder_path):
        if filename.endswith('.list'):  # 确保处理的是.list文件
            file_path = os.path.join(folder_path, filename)
            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as infile:
                content = infile.readlines()  # 读取所有行
                if content and content[-1].strip() == '':
                    # 如果最后一行已经是空行，则不额外添加
                    content_to_write = content
                else:
                    # 否则，在文件内容后添加一个空行
                    content_to_write = content + ['\n']

                # 判断文件是否在特定文件列表中
                if filename in special_files:
                    special_outfile.writelines(content_to_write)
                else:
                    general_outfile.writelines(content_to_write)

print("完成啦！两个.list文件已经根据你的要求合并完成，存储在同一个目录下。")
