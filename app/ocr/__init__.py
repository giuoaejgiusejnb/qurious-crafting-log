import os

# numpy の OpenBLAS は、読み込んだときに CPU の数だけ作業用のメモリを確保する（16 コアで 1 プロセス約 500MB）。
# 画像の切り出しは CPU の数だけプロセスを起こすので、16 コア・メモリ 16GB の PC で 8GB 近くになり、
# ほかのアプリと重なってメモリ不足（cv2.error: Insufficient memory）で止まった。読み取りは行列の計算を
# ほとんど使わないので、1 スレッドにする（約 20MB）。numpy を読み込む前に設定する必要があるので、ここに書く
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
