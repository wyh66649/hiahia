# import csv  

# path_to_file = r"D:\PythonDevTools\courselist.csv"  
# with open(path_to_file, encoding='gbk') as f:  
#     reader = csv.reader(f)   
#     headers = next(reader)   
#     for line in reader:   
#         print()
#         print(line)


import csv
import re

path_to_file = r"D:\PythonDevTools\courseList.csv"

with open(path_to_file, encoding='gbk') as f:
    reader = csv.reader(f)

    title = next(reader)          # 跳过标题行,因为原始文件第一行是学号信息
    headers = next(reader)        # 真正的表头：节次/星期 + 周一~周日

    days = headers[1:]            # 星期列表
    schedule = {d: [] for d in days}

    for line in reader:
        # 清洗：压掉换行和多余空白
        line = [re.sub(r'\s+', ' ', str(x)).strip() for x in line]     #删去换行符和空白符,同时把原本的line替换成新的删减的line
        if not any(line):
            continue
        slot = line[0] if line else ''      #从0开始检索不是空的列表
        for i, day in enumerate(days, start=1):     #遍历取值同时拿到列表序号
            if i < len(line) and line[i]:   #防止报错,确保列表的长度大于索引的长度以防报错;[i]保证取得不是空的,而是空字符
                schedule[day].append(f"{slot} | {line[i]}")    #添加课表

    for day in days:
        print(f"=== {day} ===")
        if schedule[day]:
            for c in schedule[day]:
                print("  ", c)
        else:
            print("   无课")
        print()