#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQ 邮箱附件发送脚本
支持 PDF 模式和原图模式的邮件发送
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
ATTACH_LIMIT_MB = 50  # QQ 邮箱附件大小限制（MB）
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
OUTPUT_FORMAT = os.getenv('OUTPUT_FORMAT', 'pdf_only')  # 输出模式：pdf_only / images_only
ZIP_NAME = os.getenv('ZIP_NAME', '本子.tar.gz')  # workflow 压缩包名


def log(message, level='INFO'):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] [{level}] {message}")


def get_file_size_mb(file_path):
    size_bytes = os.path.getsize(file_path)
    return round(size_bytes / (1024 * 1024), 1)


def scan_files(base_dir, file_extensions):
    """扫描指定扩展名的文件并返回文件信息列表"""
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


def scan_pdf_files(pdf_dir):
    return scan_files(pdf_dir, ['pdf'])


def scan_image_files(image_dir):
    return scan_files(image_dir, ['jpg', 'jpeg', 'png', 'webp'])


def create_pdf_zip(pdf_dir, output_path):
    log(f"开始打包 PDF 文件...")
    pdf_path = Path(pdf_dir)
    if not pdf_path.exists() or not list(pdf_path.glob('*.pdf')):
        log("PDF 目录为空，跳过打包", 'WARNING')
        return False
    try:
        if os.path.exists(output_path):
            os.remove(output_path)
        zip_base = str(Path(output_path).with_suffix(''))
        shutil.make_archive(zip_base, 'zip', pdf_dir)
        zip_size = get_file_size_mb(output_path)
        log(f"✅ 打包完成: {Path(output_path).name} ({zip_size} MB)")
        return True
    except Exception as e:
        log(f"打包失败: {e}", 'ERROR')
        return False


def build_email_content_pdf(pdf_files, zip_size_mb, is_large_file, zip_name):
    today = datetime.now().strftime('%Y-%m-%d')
    title = EMAIL_TITLE if EMAIL_TITLE else f"禁漫PDF已生成（共 {len(pdf_files)} 本 · {today}）"
    content = EMAIL_CONTENT + "\n\n" if EMAIL_CONTENT else "✅ 你的禁漫 PDF 文件已准备就绪！\n\n"

    if pdf_files:
        content += f"{'=' * 50}\n"
        content += f"📚 共 {len(pdf_files)} 本 PDF：\n"
        content += f"{'=' * 50}\n"
        for file_info in pdf_files:
            content += f"  • {file_info['name']} ({file_info['size_mb']} MB)\n"
        content += f"{'=' * 50}\n\n"

    if is_large_file:
        content += f"⚠️ 附件超过 {ATTACH_LIMIT_MB} MB，请前往 GitHub Actions 的 Artifacts 下载\n"
        content += f"📦 ZIP 大小: {zip_size_mb} MB\n"
    else:
        content += f"📦 附件已打包为 {zip_name} ({zip_size_mb} MB)\n"

    content += "\n—— GitHub Actions 自动服务"
    return title, content


def get_album_info(image_dir):
    """获取原图模式本子名称和图片数量（取二级目录名，与 PDF 命名一致）"""
    base_path = Path(image_dir)
    if not base_path.exists():
        log(f"目录不存在: {image_dir}", 'WARNING')
        return []

    album_info = []
    for first_level in base_path.iterdir():
        if first_level.is_dir():
            for second_level in first_level.iterdir():
                if second_level.is_dir():
                    img_count = len(list(second_level.glob('**/*.webp'))) + \
                                len(list(second_level.glob('**/*.jpg'))) + \
                                len(list(second_level.glob('**/*.jpeg'))) + \
                                len(list(second_level.glob('**/*.png')))
                    album_info.append({'name': second_level.name, 'count': img_count})

    return sorted(album_info, key=lambda x: x['name'])


def build_email_content_images(image_dir, archive_size_mb, is_large_file, archive_name):
    today = datetime.now().strftime('%Y-%m-%d')
    title = EMAIL_TITLE if EMAIL_TITLE else f"禁漫原图已下载（{today}）"
    content = EMAIL_CONTENT + "\n\n" if EMAIL_CONTENT else "✅ 你的禁漫原图文件已准备就绪！\n\n"

    album_info = get_album_info(image_dir)
    if album_info:
        content += f"{'=' * 50}\n"
        content += f"🖼️ 本子列表（原图模式）：\n"
        content += f"{'=' * 50}\n"
        for album in album_info:
            content += f"  • {album['name']} （{album['count']} 张图片）\n"
        content += f"{'=' * 50}\n\n"

    if is_large_file:
        content += f"⚠️ 压缩包超过 {ATTACH_LIMIT_MB} MB，请前往 GitHub Actions 的 Artifacts（https://github.com/myslice666/JMComic-Crawler-Python/actions/workflows/download_dispatch.yml） 下载\n"
        content += f"📦 压缩包: {archive_name} ({archive_size_mb} MB)\n"
    else:
        content += f"📦 附件已打包为 {archive_name} ({archive_size_mb} MB)\n"

    content += "\n—— GitHub Actions 自动服务"
    return title, content


def send_email(title, content, attachment_path=None, retry_count=0):
    smtp_conn = None
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        msg['Subject'] = title
        msg.attach(MIMEText(content, 'plain', 'utf-8'))

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

        log("正在连接 SMTP 服务器...")
        smtp_conn = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60)
        smtp_conn.login(EMAIL_FROM, EMAIL_PASS)
        log("✅ SMTP 登录成功")
        smtp_conn.send_message(msg)
        log("✅ 邮件发送成功")
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
        if smtp_conn:
            try:
                smtp_conn.quit()
            except:
                pass
        if retry_count < MAX_RETRIES:
            retry_count += 1
            log(f"🔄 {RETRY_DELAY} 秒后进行第 {retry_count} 次重试...", 'WARNING')
            time.sleep(RETRY_DELAY)
            return send_email(title, content, attachment_path, retry_count)
        else:
            log(f"❌ 已达到最大重试次数 ({MAX_RETRIES})，发送失败", 'ERROR')
            return False


def handle_pdf_mode():
    log("📄 当前模式: PDF 模式")
    pdf_dir = Path(JM_DOWNLOAD_DIR) / 'pdf'
    log(f"📁 扫描 PDF 目录: {pdf_dir}")
    pdf_files = scan_pdf_files(pdf_dir)

    if not pdf_files:
        log("⚠️ 未找到 PDF 文件", 'WARNING')
        return None, None, None, []

    log(f"✅ 找到 {len(pdf_files)} 个 PDF 文件:")
    total_size = 0
    for file_info in pdf_files:
        log(f"  • {file_info['name']} ({file_info['size_mb']} MB)")
        total_size += file_info['size_mb']
    log(f"📊 总大小: {total_size:.1f} MB")

    zip_name = 'all_pdf.zip'
    zip_path = Path(JM_DOWNLOAD_DIR) / zip_name
    if not create_pdf_zip(pdf_dir, zip_path):
        log("❌ 打包失败", 'ERROR')
        return None, None, None, pdf_files

    zip_size_mb = get_file_size_mb(zip_path)
    is_large_file = zip_size_mb > ATTACH_LIMIT_MB
    if is_large_file:
        log(f"⚠️ ZIP 文件过大 ({zip_size_mb} MB > {ATTACH_LIMIT_MB} MB)", 'WARNING')
        log("将发送通知邮件（不带附件）")

    return zip_path, zip_size_mb, is_large_file, pdf_files


def handle_images_mode():
    log("🖼️  当前模式: 原图模式")
    archive_path = Path(JM_DOWNLOAD_DIR) / ZIP_NAME
    if not archive_path.exists():
        log(f"⚠️ 未找到压缩包: {ZIP_NAME}", 'WARNING')
        return None, None, None, []

    image_files = scan_image_files(JM_DOWNLOAD_DIR)
    if not image_files:
        log("⚠️ 未找到图片文件", 'WARNING')
    else:
        log(f"✅ 找到 {len(image_files)} 张图片")
        formats = {}
        for img in image_files:
            ext = Path(img['name']).suffix.lower()
            formats[ext] = formats.get(ext, 0) + 1
        for ext, count in sorted(formats.items()):
            log(f"  • {ext.upper()}: {count} 张")

    archive_size_mb = get_file_size_mb(archive_path)
    is_large_file = archive_size_mb > ATTACH_LIMIT_MB
    log(f"📦 压缩包: {ZIP_NAME} ({archive_size_mb} MB)")
    if is_large_file:
        log(f"⚠️ 压缩包过大 ({archive_size_mb} MB > {ATTACH_LIMIT_MB} MB)", 'WARNING')
        log("将发送通知邮件（不带附件）")

    return archive_path, archive_size_mb, is_large_file, image_files


def main():
    log("=" * 60)
    log("📧 开始邮件发送任务")
    log("=" * 60)

    if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PASS]):
        log("⚠️ 邮件配置不完整，跳过发送", 'WARNING')
        log("需要配置: EMAIL_FROM, EMAIL_TO, EMAIL_PASS")
        return 0

    log(f"📤 发件人: {EMAIL_FROM}")
    log(f"📥 收件人: {EMAIL_TO}")
    log(f"📦 输出模式: {OUTPUT_FORMAT}")

    if OUTPUT_FORMAT == 'images_only':
        attachment_path, size_mb, is_large, files = handle_images_mode()
        if attachment_path is None:
            title = f"禁漫下载任务完成 · {datetime.now().strftime('%Y-%m-%d')}"
            content = "下载任务已完成，但未找到压缩包文件。\n\n—— GitHub Actions 自动服务"
            send_email(title, content)
            return 0
        title, content = build_email_content_images(JM_DOWNLOAD_DIR, size_mb, is_large, ZIP_NAME)
    else:  # pdf_only
        attachment_path, size_mb, is_large, files = handle_pdf_mode()
        if attachment_path is None:
            title = f"禁漫下载任务完成 · {datetime.now().strftime('%Y-%m-%d')}"
            content = "下载任务已完成，但未生成 PDF 文件或打包失败。\n\n—— GitHub Actions 自动服务"
            send_email(title, content)
            return 0
        zip_name = Path(attachment_path).name
        title, content = build_email_content_pdf(files, size_mb, is_large, zip_name)

    log("=" * 60)
    if is_large:
        success = send_email(title, content)
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
        sys.exit(0)
