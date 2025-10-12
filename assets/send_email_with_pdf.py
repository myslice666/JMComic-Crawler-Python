#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQ 邮箱附件发送脚本
支持 PDF 模式和原图模式的邮件发送（修复原图模式目录识别问题）
"""

import os
import sys
import smtplib
import shutil
import time
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime

# ============================================
# 配置区域
# ============================================
SMTP_HOST = 'smtp.qq.com'
SMTP_PORT = 465
ATTACH_LIMIT_MB = 45  # QQ 邮箱附件大小限制（MB）
MAX_RETRIES = 1  # 发送失败重试次数
RETRY_DELAY = 3  # 重试间隔（秒）

# ============================================
# 从环境变量读取配置
# ============================================
JM_DOWNLOAD_DIR = os.getenv('JM_DOWNLOAD_DIR', '/home/runner/work/jmcomic/download/')
EMAIL_FROM = os.getenv('EMAIL_FROM', '')
EMAIL_TO = os.getenv('EMAIL_TO', '')
EMAIL_PASS = os.getenv('EMAIL_PASS', '')
EMAIL_TITLE = os.getenv('EMAIL_TITLE', '')
EMAIL_CONTENT = os.getenv('EMAIL_CONTENT', '')
OUTPUT_FORMAT = os.getenv('OUTPUT_FORMAT', 'pdf_only')  # 输出格式
ZIP_NAME = os.getenv('ZIP_NAME', '本子.tar.gz')  # 从环境变量读取压缩包名称


def log(message, level='INFO'):
    """输出日志"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] [{level}] {message}")


def get_file_size_mb(file_path):
    """获取文件大小（MB，保留一位小数）"""
    size_bytes = os.path.getsize(file_path)
    return round(size_bytes / (1024 * 1024), 1)


def scan_files(base_dir, file_extensions):
    """扫描指定扩展名的文件并返回文件信息列表（用于PDF模式）"""
    base_path = Path(base_dir)
    if not base_path.exists():
        log(f"目录不存在: {base_dir}", 'WARNING')
        return []
    
    file_info = []
    for ext in file_extensions:
        files = sorted(base_path.rglob(f'*.{ext}'))
        for file in files:
            size_mb = get_file_size_mb(file)
            file_info.append({
                'path': str(file),
                'name': file.name,
                'size_mb': size_mb
            })
    
    return file_info


def get_album_info(base_dir):
    """从下载目录提取本子信息（优化：兼容任意目录结构，按图片存在性判断）- 用于原图模式"""
    base_path = Path(base_dir)
    if not base_path.exists():
        log(f"目录不存在: {base_dir}", 'WARNING')
        return []
    
    album_list = []
    image_extensions = ['.jpg', '.jpeg', '.png', '.webp']
    
    # 遍历所有子目录（不再依赖 *_A*_* 固定格式，更通用）
    for potential_album_dir in base_path.iterdir():
        if not potential_album_dir.is_dir():
            continue  # 只处理目录
        
        # 检查当前目录下是否有图片文件（有则视为本子目录）
        image_files = list(potential_album_dir.rglob('*'))
        image_files = [f for f in image_files if f.suffix.lower() in image_extensions]
        if not image_files:
            continue  # 无图片则跳过
        
        # 解析本子名称：优先从目录名提取（兼容原 dir_rule 结构，无则用目录名本身）
        dir_name = potential_album_dir.name
        album_name = dir_name  # 默认用目录名作为本子名
        dir_parts = dir_name.split('_')
        
        # 尝试提取 Atitle（兼容原 dir_rule: Bd_Aauthor_Atitle_Pindex）
        atitle_index = None
        # 1. 优先匹配明确的 Atitle 片段（如 Atitle_xxx）
        for i, part in enumerate(dir_parts):
            if part.startswith('A') and 'title' in part.lower():
                atitle_index = i
                break
        # 2. 兼容 Aauthor 后的片段（如 Aauthor_xxx_Atitle）
        if atitle_index is None:
            for i, part in enumerate(dir_parts):
                if part.startswith('Aauthor'):
                    atitle_index = i + 1
                    break
        
        # 若找到 Atitle 相关片段，重构本子名（排除 Pindex 章节号）
        if atitle_index and atitle_index < len(dir_parts):
            album_name_parts = [p for p in dir_parts[atitle_index:] if not p.startswith('P')]
            if album_name_parts:  # 确保有有效片段
                album_name = '_'.join(album_name_parts)
        
        # 统计本子的图片信息
        total_image_count = len(image_files)
        total_size_mb = round(sum(f.stat().st_size for f in image_files) / (1024 * 1024), 1)
        
        album_list.append({
            'name': album_name,
            'image_count': total_image_count,
            'total_size_mb': total_size_mb,
            'dir_path': str(potential_album_dir)
        })
    
    # 若根目录有图片（无子目录场景），视为一个本子
    root_image_files = [f for f in base_path.rglob('*') if f.suffix.lower() in image_extensions and f.parent == base_path]
    if root_image_files and not album_list:
        total_image_count = len(root_image_files)
        total_size_mb = round(sum(f.stat().st_size for f in root_image_files) / (1024 * 1024), 1)
        album_list.append({
            'name': '根目录本子',
            'image_count': total_image_count,
            'total_size_mb': total_size_mb,
            'dir_path': str(base_path)
        })
    
    return album_list


def create_pdf_zip(pdf_dir, output_path):
    """将 PDF 目录打包为 ZIP（PDF模式专用）"""
    log(f"开始打包 PDF 文件...")
    
    pdf_path = Path(pdf_dir)
    if not pdf_path.exists() or not list(pdf_path.glob('*.pdf')):
        log("PDF 目录为空，跳过打包", 'WARNING')
        return False
    
    try:
        # 删除旧ZIP文件
        if os.path.exists(output_path):
            os.remove(output_path)
        
        # 创建新ZIP
        zip_base = str(Path(output_path).with_suffix(''))
        shutil.make_archive(zip_base, 'zip', pdf_dir)
        
        zip_size = get_file_size_mb(output_path)
        log(f"✅ 打包完成: {Path(output_path).name} ({zip_size} MB)")
        return True
        
    except Exception as e:
        log(f"打包失败: {e}", 'ERROR')
        return False


def build_email_content_pdf(pdf_files, zip_size_mb, is_large_file, zip_name):
    """构建 PDF 模式的邮件正文"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 标题
    if EMAIL_TITLE:
        title = EMAIL_TITLE
    else:
        pdf_count = len(pdf_files)
        title = f"禁漫PDF已生成（共 {pdf_count} 本 · {today}）"
    
    # 正文
    if EMAIL_CONTENT:
        content = EMAIL_CONTENT + "\n\n"
    else:
        content = "✅ 你的禁漫 PDF 文件已准备就绪！\n\n"
    
    # PDF文件列表
    if pdf_files:
        content += f"{'=' * 50}\n"
        content += f"📚 共 {len(pdf_files)} 本 PDF：\n"
        content += f"{'=' * 50}\n"
        for file_info in pdf_files:
            content += f"  • {file_info['name']} ({file_info['size_mb']} MB)\n"
        content += f"{'=' * 50}\n\n"
    
    # 压缩包提示
    if is_large_file:
        content += f"⚠️ 附件超过 {ATTACH_LIMIT_MB} MB，请前往 GitHub Actions 的 Artifacts 下载\n"
        content += f"📦 ZIP 大小: {zip_size_mb} MB\n"
    else:
        content += f"📦 附件已打包为 {zip_name} ({zip_size_mb} MB)\n"
    
    content += "\n—— GitHub Actions 自动服务"
    
    return title, content


def build_email_content_images(album_list, archive_size_mb, is_large_file, archive_name):
    """构建原图模式的邮件正文（优化：空数据场景提示更清晰）"""
    today = datetime.now().strftime('%Y-%m-%d')
    total_album_count = len(album_list)
    total_image_count = sum(album['image_count'] for album in album_list) if album_list else 0
    
    # 标题（空数据时调整表述）
    if EMAIL_TITLE:
        title = EMAIL_TITLE
    else:
        if total_album_count > 0:
            title = f"禁漫原图已下载（共 {total_album_count} 本 · {today}）"
        else:
            title = f"禁漫下载任务完成（原图模式 · {today}）"
    
    # 正文（空数据时明确提示）
    if EMAIL_CONTENT:
        content = EMAIL_CONTENT + "\n\n"
    else:
        if total_album_count > 0:
            content = "✅ 你的禁漫原图文件已准备就绪！\n\n"
        else:
            content = "ℹ️ 禁漫下载任务已完成（原图模式），但未识别到具体本子或图片文件。\n\n"
    
    # 本子列表（有数据时展示，空数据时跳过）
    if album_list:
        content += f"{'=' * 50}\n"
        content += f"🖼️  共 {total_album_count} 本本子：\n"
        content += f"{'=' * 50}\n"
        for album in album_list:
            content += f"  • {album['name']}（{album['image_count']} 张图 · {album['total_size_mb']} MB）\n"
        content += f"{'=' * 50}\n\n"
    
    # 统计信息（空数据时简化）
    content += f"{'=' * 50}\n"
    content += f"📊 原图模式统计：\n"
    content += f"{'=' * 50}\n"
    if album_list:
        content += f"  • 本子总数: {total_album_count} 本\n"
        content += f"  • 图片总数: {total_image_count} 张\n"
        content += f"  • 所有图片总大小: {sum(a['total_size_mb'] for a in album_list):.1f} MB\n"
    else:
        content += f"  • 本子总数: 0 本\n"
        content += f"  • 图片总数: 0 张\n"
    content += f"{'=' * 50}\n\n"
    
    # 压缩包提示（空数据时仍显示压缩包信息）
    if os.path.exists(Path(JM_DOWNLOAD_DIR) / archive_name):
        if is_large_file:
            content += f"⚠️ 压缩包超过 {ATTACH_LIMIT_MB} MB，请前往 GitHub Actions 的 Artifacts 下载\n"
            content += f"📦 压缩包: {archive_name} ({archive_size_mb} MB)\n"
        else:
            content += f"📦 压缩包: {archive_name} ({archive_size_mb} MB)（无有效图片文件）\n"
    else:
        content += f"⚠️ 未找到压缩包: {archive_name}\n"
    
    # 统一结尾标识
    content += "\n—— GitHub Actions 自动服务"
    
    return title, content


def send_email(title, content, attachment_path=None, retry_count=0):
    """发送邮件（支持重试）"""
    smtp_conn = None
    try:
        # 创建邮件对象
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        msg['Subject'] = title
        
        # 添加正文
        msg.attach(MIMEText(content, 'plain', 'utf-8'))
        
        # 添加附件（不超过大小限制）
        if attachment_path and os.path.exists(attachment_path):
            attach_size_mb = get_file_size_mb(attachment_path)
            attach_name = Path(attachment_path).name
            
            if attach_size_mb <= ATTACH_LIMIT_MB:
                log(f"添加附件: {attach_name} ({attach_size_mb} MB)")
                with open(attachment_path, 'rb') as f:
                    attachment = MIMEApplication(f.read())
                    attachment.add_header(
                        'Content-Disposition',
                        'attachment',
                        filename=('utf-8', '', attach_name)
                    )
                    msg.attach(attachment)
        
        # 连接SMTP服务器
        log("正在连接 SMTP 服务器...")
        smtp_conn = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60)
        smtp_conn.login(EMAIL_FROM, EMAIL_PASS)
        log("✅ SMTP 登录成功")
        
        # 发送邮件
        smtp_conn.send_message(msg)
        log("✅ 邮件发送成功")
        
        # 关闭连接
        try:
            smtp_conn.quit()
        except:
            pass
        
        return True
            
    except smtplib.SMTPAuthenticationError:
        log("❌ SMTP 认证失败，请检查邮箱授权码", 'ERROR')
        return False
        
    except Exception as e:
        log(f"❌ 邮件发送失败: {e}", 'ERROR')
        
        # 关闭连接
        if smtp_conn:
            try:
                smtp_conn.quit()
            except:
                pass
        
        # 重试逻辑
        if retry_count < MAX_RETRIES:
            retry_count += 1
            log(f"🔄 {RETRY_DELAY} 秒后进行第 {retry_count} 次重试...", 'WARNING')
            time.sleep(RETRY_DELAY)
            return send_email(title, content, attachment_path, retry_count)
        else:
            log(f"❌ 已达到最大重试次数 ({MAX_RETRIES})，发送失败", 'ERROR')
            return False


def handle_pdf_mode():
    """处理 PDF 模式"""
    log("📄 当前模式: PDF 模式")
    
    # 扫描PDF文件
    pdf_dir = Path(JM_DOWNLOAD_DIR) / 'pdf'
    log(f"📁 扫描 PDF 目录: {pdf_dir}")
    
    pdf_files = scan_files(pdf_dir, ['pdf'])
    
    if not pdf_files:
        log("⚠️ 未找到 PDF 文件", 'WARNING')
        return None, None, None, []
    
    # 显示PDF列表
    log(f"✅ 找到 {len(pdf_files)} 个 PDF 文件:")
    total_size = 0
    for file_info in pdf_files:
        log(f"  • {file_info['name']} ({file_info['size_mb']} MB)")
        total_size += file_info['size_mb']
    log(f"📊 总大小: {total_size:.1f} MB")
    
    # 打包ZIP
    zip_name = 'all_pdf.zip'
    zip_path = Path(JM_DOWNLOAD_DIR) / zip_name
    
    if not create_pdf_zip(pdf_dir, zip_path):
        log("❌ 打包失败", 'ERROR')
        return None, None, None, pdf_files
    
    # 检查ZIP大小
    zip_size_mb = get_file_size_mb(zip_path)
    is_large_file = zip_size_mb > ATTACH_LIMIT_MB
    
    if is_large_file:
        log(f"⚠️ ZIP 文件过大 ({zip_size_mb} MB > {ATTACH_LIMIT_MB} MB)", 'WARNING')
        log("将发送通知邮件（不带附件）")
    
    return zip_path, zip_size_mb, is_large_file, pdf_files


def handle_images_mode():
    """处理原图模式（优化：空数据场景处理更友好）"""
    log("🖼️ 当前模式: 原图模式")
    
    # 提取本子信息（优化后：兼容任意目录结构）
    log(f"📁 扫描本子目录: {JM_DOWNLOAD_DIR}（兼容任意目录结构）")
    album_list = get_album_info(JM_DOWNLOAD_DIR)
    
    if not album_list:
        log("⚠️ 未找到包含图片的本子目录（或根目录无图片）", 'WARNING')
        # 即使无本子信息，仍检查压缩包（避免直接返回None）
        archive_path = Path(JM_DOWNLOAD_DIR) / ZIP_NAME
        archive_size_mb = get_file_size_mb(archive_path) if archive_path.exists() else 0
        is_large_file = archive_size_mb > ATTACH_LIMIT_MB if archive_path.exists() else False
        return archive_path if archive_path.exists() else None, archive_size_mb, is_large_file, album_list
    
    # 显示本子列表
    log(f"✅ 找到 {len(album_list)} 本本子:")
    for album in album_list:
        log(f"  • {album['name']}（{album['image_count']} 张图 · {album['total_size_mb']} MB）")
    total_image_size = sum(a['total_size_mb'] for a in album_list)
    log(f"📊 本子总大小: {total_image_size:.1f} MB")
    
    # 检查压缩包
    archive_path = Path(JM_DOWNLOAD_DIR) / ZIP_NAME
    if not archive_path.exists():
        log(f"⚠️ 未找到压缩包: {ZIP_NAME}", 'WARNING')
        return None, 0, False, album_list
    
    # 检查压缩包大小
    archive_size_mb = get_file_size_mb(archive_path)
    is_large_file = archive_size_mb > ATTACH_LIMIT_MB
    
    log(f"📦 压缩包: {ZIP_NAME} ({archive_size_mb} MB)")
    if is_large_file:
        log(f"⚠️ 压缩包过大 ({archive_size_mb} MB > {ATTACH_LIMIT_MB} MB)", 'WARNING')
        log("将发送通知邮件（不带附件）")
    
    return archive_path, archive_size_mb, is_large_file, album_list


def main():
    """主函数"""
    log("=" * 60)
    log("📧 开始邮件发送任务")
    log("=" * 60)
    
    # 检查邮件配置
    if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PASS]):
        log("⚠️ 邮件配置不完整，跳过发送", 'WARNING')
        log("需要配置: EMAIL_FROM, EMAIL_TO, EMAIL_PASS")
        return 0
    
    log(f"📤 发件人: {EMAIL_FROM}")
    log(f"📥 收件人: {EMAIL_TO}")
    log(f"📦 输出模式: {OUTPUT_FORMAT}")
    
    # 根据模式处理
    if OUTPUT_FORMAT == 'images_only':
        attachment_path, size_mb, is_large, album_list = handle_images_mode()
        
        # 构建原图模式邮件内容（无论是否有本子信息，都生成清晰提示）
        title, content = build_email_content_images(
            album_list, size_mb, is_large, ZIP_NAME
        )
        
        # 发送邮件（即使无附件也发送通知）
        log("=" * 60)
        if is_large or not attachment_path:
            success = send_email(title, content)
        else:
            success = send_email(title, content, attachment_path)
        
    else:  # pdf_only
        attachment_path, size_mb, is_large, pdf_files = handle_pdf_mode()
        
        if attachment_path is None:
            # 发送失败通知
            title = f"禁漫下载任务完成 · {datetime.now().strftime('%Y-%m-%d')}"
            content = "下载任务已完成，但未生成 PDF 文件或打包失败。\n\n—— GitHub Actions 自动服务"
            send_email(title, content)
            return 0
        
        # 构建PDF模式邮件内容
        zip_name = Path(attachment_path).name
        title, content = build_email_content_pdf(
            pdf_files, size_mb, is_large, zip_name
        )
        
        # 发送邮件
        log("=" * 60)
        if is_large:
            success = send_email(title, content)  # 超大文件不附加
        else:
            success = send_email(title, content, attachment_path)
    
    log("=" * 60)
    
    if success:
        log("✅ 邮件任务完成")
        return 0
    else:
        log("⚠️ 邮件发送失败，但不影响主流程", 'WARNING')
        return 0


if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        log("\n❌ 任务被用户中断", 'ERROR')
        sys.exit(1)
    except Exception as e:
        log(f"❌ 发生未预期的错误: {e}", 'ERROR')
        import traceback
        log(traceback.format_exc(), 'ERROR')
        sys.exit(0)  # 返回0不中断workflow
