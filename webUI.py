import io
import os

# os.system("wget -P cvec/ https://huggingface.co/spaces/innnky/nanami/resolve/main/checkpoint_best_legacy_500.pt")
import gradio as gr
import gradio.processing_utils as gr_pu
import librosa
import numpy as np
import soundfile
from inference.infer_tool import Svc
import logging

import subprocess
import edge_tts
import asyncio
from scipy.io import wavfile
import librosa
import torch
import time
import traceback

logging.getLogger('numba').setLevel(logging.WARNING)
logging.getLogger('markdown_it').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('matplotlib').setLevel(logging.WARNING)
logging.getLogger('multipart').setLevel(logging.WARNING)

model = None
spk = None
debug = False

cuda = {}
if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        device_name = torch.cuda.get_device_properties(i).name
        cuda[f"CUDA:{i} {device_name}"] = f"cuda:{i}"

def modelAnalysis(model_path,config_path,cluster_model_path,device,enhance):
    global model
    try:
        device = cuda[device] if "CUDA" in device else device
        model = Svc(model_path.name, config_path.name, device=device if device!="Auto" else None, cluster_model_path = cluster_model_path.name if cluster_model_path != None else "",nsf_hifigan_enhance=enhance)
        spks = list(model.spk2id.keys())
        device_name = torch.cuda.get_device_properties(model.dev).name if "cuda" in str(model.dev) else str(model.dev)
        msg = f"成功加载模型到设备{device_name}上\n"
        if cluster_model_path is None:
            msg += "未加载聚类模型\n"
        else:
            msg += f"聚类模型{cluster_model_path.name}加载成功\n"
        msg += "当前模型的可用音色：\n"
        for i in spks:
            msg += i + " "
        return sid.update(choices = spks,value=spks[0]), msg
    except Exception as e:
        if debug: traceback.print_exc()
        raise gr.Error(e)

    
def modelUnload():
    global model
    if model is None:
        return sid.update(choices = [],value=""),"没有模型需要卸载!"
    else:
        model.unload_model()
        model = None
        torch.cuda.empty_cache()
        return sid.update(choices = [],value=""),"模型卸载完毕!"


def vc_fn(sid, input_audio, vc_transform, auto_f0,cluster_ratio, slice_db, noise_scale,pad_seconds,cl_num,lg_num,lgr_num,F0_mean_pooling,enhancer_adaptive_key):
    global model
    try:
        if input_audio is None:
            raise gr.Error("你需要上传音频")
        if model is None:
            raise gr.Error("你需要指定模型")
        sampling_rate, audio = input_audio
        # print(audio.shape,sampling_rate)
        audio = (audio / np.iinfo(audio.dtype).max).astype(np.float32)
        if len(audio.shape) > 1:
            audio = librosa.to_mono(audio.transpose(1, 0))
        temp_path = "temp.wav"
        soundfile.write(temp_path, audio, sampling_rate, format="wav")
        _audio = model.slice_inference(temp_path, sid, vc_transform, slice_db, cluster_ratio, auto_f0, noise_scale,pad_seconds,cl_num,lg_num,lgr_num,F0_mean_pooling,enhancer_adaptive_key)
        model.clear_empty()
        os.remove(temp_path)
        #构建保存文件的路径，并保存到results文件夹内
        try:
            timestamp = str(int(time.time()))
            filename = sid + "_" + timestamp + ".wav"
            output_file = os.path.join("./results", filename)
            soundfile.write(output_file, _audio, model.target_sample, format="wav")
            return f"推理成功，音频文件保存为results/{filename}", (model.target_sample, _audio)
        except Exception as e:
            if debug: traceback.print_exc()
            raise gr.Error(e)
    except Exception as e:
        if debug: traceback.print_exc()
        raise gr.Error(e)


def tts_func(_text,_rate,_voice):
    #使用edge-tts把文字转成音频
    # voice = "zh-CN-XiaoyiNeural"#女性，较高音
    # voice = "zh-CN-YunxiNeural"#男性
    voice = "zh-CN-YunxiNeural"#男性
    if ( _voice == "女" ) : voice = "zh-CN-XiaoyiNeural"
    output_file = _text[0:10]+".wav"
    # communicate = edge_tts.Communicate(_text, voice)
    # await communicate.save(output_file)
    if _rate>=0:
        ratestr="+{:.0%}".format(_rate)
    elif _rate<0:
        ratestr="{:.0%}".format(_rate)#减号自带

    p=subprocess.Popen("edge-tts "+
                        " --text "+_text+
                        " --write-media "+output_file+
                        " --voice "+voice+
                        " --rate="+ratestr
                        ,shell=True,
                        stdout=subprocess.PIPE,
                        stdin=subprocess.PIPE)
    p.wait()
    return output_file

def text_clear(text):
    return re.sub(r"[\n\,\(\) ]", "", text)

def vc_fn2(sid, input_audio, vc_transform, auto_f0,cluster_ratio, slice_db, noise_scale,pad_seconds,cl_num,lg_num,lgr_num,text2tts,tts_rate,tts_voice,F0_mean_pooling,enhancer_adaptive_key):
    #使用edge-tts把文字转成音频
    text2tts=text_clear(text2tts)
    output_file=tts_func(text2tts,tts_rate,tts_voice)

    #调整采样率
    sr2=44100
    wav, sr = librosa.load(output_file)
    wav2 = librosa.resample(wav, orig_sr=sr, target_sr=sr2)
    save_path2= text2tts[0:10]+"_44k"+".wav"
    wavfile.write(save_path2,sr2,
                (wav2 * np.iinfo(np.int16).max).astype(np.int16)
                )

    #读取音频
    sample_rate, data=gr_pu.audio_from_file(save_path2)
    vc_input=(sample_rate, data)

    a,b=vc_fn(sid, vc_input, vc_transform,auto_f0,cluster_ratio, slice_db, noise_scale,pad_seconds,cl_num,lg_num,lgr_num,F0_mean_pooling,enhancer_adaptive_key)
    os.remove(output_file)
    os.remove(save_path2)
    return a,b

def debug_change():
    global debug
    debug = debug_button.value

with gr.Blocks(
    theme=gr.themes.Base(
        primary_hue = gr.themes.colors.green,
        font=["Source Sans Pro", "Arial", "sans-serif"],
        font_mono=['JetBrains mono', "Consolas", 'Courier New']
    ),
) as app:
    with gr.Tabs():
        with gr.TabItem("Inference"):
            gr.Markdown(value="""
                So-vits-svc 4.0 推理 webui
                """)
            with gr.Row(variant="panel"):
                with gr.Column():
                    gr.Markdown(value="""
                        <font size=2> 模型设置</font>
                        """)
                    model_path = gr.File(label="选择模型文件")
                    config_path = gr.File(label="选择配置文件")
                    cluster_model_path = gr.File(label="选择聚类模型文件（没有可以不选）")
                    device = gr.Dropdown(label="推理设备，默认为自动选择CPU和GPU", choices=["Auto",*cuda.keys(),"CPU"], value="Auto")
                    enhance = gr.Checkbox(label="是否使用NSF_HIFIGAN增强,该选项对部分训练集少的模型有一定的音质增强效果，但是对训练好的模型有反面效果，默认关闭", value=False)
                with gr.Column():
                    gr.Markdown(value="""
                        <font size=3>左侧文件全部选择完毕后(全部文件模块显示download)，点击“加载模型”进行解析：</font>
                        """)
                    model_load_button = gr.Button(value="加载模型", variant="primary")
                    model_unload_button = gr.Button(value="卸载模型", variant="primary")
                    sid = gr.Dropdown(label="音色（说话人）")
                    sid_output = gr.Textbox(label="Output Message")


            with gr.Row(variant="panel"):
                with gr.Column():
                    gr.Markdown(value="""
                        <font size=2> 推理设置</font>
                        """)
                    auto_f0 = gr.Checkbox(label="自动f0预测，配合聚类模型f0预测效果更好,会导致变调功能失效（仅限转换语音，歌声勾选此项会究极跑调）", value=False)
                    F0_mean_pooling = gr.Checkbox(label="是否对F0使用均值滤波器(池化)，对部分哑音有改善。注意，启动该选项会导致推理速度下降，默认关闭", value=False)
                    vc_transform = gr.Number(label="变调（整数，可以正负，半音数量，升高八度就是12）", value=0)
                    cluster_ratio = gr.Number(label="聚类模型混合比例，0-1之间，0即不启用聚类。使用聚类模型能提升音色相似度，但会导致咬字下降（如果使用建议0.5左右）", value=0)
                    slice_db = gr.Number(label="切片阈值", value=-40)
                    noise_scale = gr.Number(label="noise_scale 建议不要动，会影响音质，玄学参数", value=0.4)
                with gr.Column():
                    pad_seconds = gr.Number(label="推理音频pad秒数，由于未知原因开头结尾会有异响，pad一小段静音段后就不会出现", value=0.5)
                    cl_num = gr.Number(label="音频自动切片，0为不切片，单位为秒(s)", value=0)
                    lg_num = gr.Number(label="两端音频切片的交叉淡入长度，如果自动切片后出现人声不连贯可调整该数值，如果连贯建议采用默认值0，注意，该设置会影响推理速度，单位为秒/s", value=0)
                    lgr_num = gr.Number(label="自动音频切片后，需要舍弃每段切片的头尾。该参数设置交叉长度保留的比例，范围0-1,左开右闭", value=0.75)
                    enhancer_adaptive_key = gr.Number(label="使增强器适应更高的音域(单位为半音数)|默认为0", value=0)
            with gr.Tabs():
                with gr.TabItem("音频转音频"):
                    vc_input3 = gr.Audio(label="选择音频")
                    vc_submit = gr.Button("音频转换", variant="primary")
                with gr.TabItem("文字转音频"):
                    text2tts=gr.Textbox(label="在此输入要转译的文字。注意，使用该功能建议打开F0预测，不然会很怪")
                    tts_rate = gr.Number(label="tts语速", value=0)
                    tts_voice = gr.Radio(label="性别",choices=["男","女"], value="男")
                    vc_submit2 = gr.Button("文字转换", variant="primary")
            with gr.Row():
                with gr.Column():
                    vc_output1 = gr.Textbox(label="Output Message")
                with gr.Column():
                    vc_output2 = gr.Audio(label="Output Audio", interactive=False)
            with gr.Row(variant="panel"):
                with gr.Column():
                    gr.Markdown(value="""
                        <font size=2> WebUI设置</font>
                        """)
                    debug_button = gr.Checkbox(label="Debug模式，如果向社区反馈BUG需要打开，打开后控制台可以显示具体错误提示", value=debug)
        vc_submit.click(vc_fn, [sid, vc_input3, vc_transform,auto_f0,cluster_ratio, slice_db, noise_scale,pad_seconds,cl_num,lg_num,lgr_num,F0_mean_pooling,enhancer_adaptive_key], [vc_output1, vc_output2])
        vc_submit2.click(vc_fn2, [sid, vc_input3, vc_transform,auto_f0,cluster_ratio, slice_db, noise_scale,pad_seconds,cl_num,lg_num,lgr_num,text2tts,tts_rate,tts_voice,F0_mean_pooling,enhancer_adaptive_key], [vc_output1, vc_output2])
        debug_button.change(debug_change,[],[])
        model_load_button.click(modelAnalysis,[model_path,config_path,cluster_model_path,device,enhance],[sid,sid_output])
        model_unload_button.click(modelUnload,[],[sid,sid_output])
    app.launch()


