from __future__ import print_function
import argparse
import os
import time

import torch
import torch.backends.cudnn as cudnn
import numpy as np
import skimage
import torch.cuda as ct
from net_builder import SUPPORT_NETS, build_net
from losses.multiscaleloss import multiscaleloss
import torch.nn.functional as F
import torch.nn as nn
from dataloader.StereoLoader import StereoDataset
from dataloader.SceneFlowLoader import SceneFlowDataset
from utils.preprocess import scale_disp, save_pfm
from utils.common import count_parameters 
from torch.utils.data import DataLoader
from torchvision import transforms
import psutil

process = psutil.Process(os.getpid())
cudnn.benchmark = True

def detect(opt):

    net_name = opt.net
    model = opt.model
    result_path = opt.rp
    file_list = opt.filelist
    filepath = opt.filepath

    if not os.path.exists(result_path):
        os.makedirs(result_path)

    devices = [int(item) for item in opt.devices.split(',')]
    ngpu = len(devices)

    # build net according to the net name
    if net_name == "psmnet" or net_name == "ganet":
        net = build_net(net_name)(192)
    elif net_name in ["fadnet", "dispnetc"]:
        net = build_net(net_name)(batchNorm=False, lastRelu=True)

    net = torch.nn.DataParallel(net, device_ids=devices).cuda()

    model_data = torch.load(model)
    print(model_data.keys())
    if 'state_dict' in model_data.keys():
        net.load_state_dict(model_data['state_dict'])
    else:
        net.load_state_dict(model_data)

    num_of_parameters = count_parameters(net)
    print('Model: %s, # of parameters: %d' % (net_name, num_of_parameters))

    net.eval()

    batch_size = int(opt.batchSize)
    test_dataset = StereoDataset(txt_file=file_list, root_dir=filepath, phase='detect')
    test_loader = DataLoader(test_dataset, batch_size = batch_size, \
                        shuffle = False, num_workers = 1, \
                        pin_memory = True)

    s = time.time()

    avg_time = []
    display = 50
    warmup = 10
    for i, sample_batched in enumerate(test_loader):
        #if i > 215:
        #    break

        input = torch.cat((sample_batched['img_left'], sample_batched['img_right']), 1)

        # print('input Shape: {}'.format(input.size()))
        num_of_samples = input.size(0)

        #output, input_var = detect_batch(net, sample_batched, opt.net, (540, 960))

        input = input.cuda()
        input_var = torch.autograd.Variable(input, volatile=True)

        if i > warmup:
            ss = time.time()

        with torch.no_grad():
            if opt.net == "psmnet" or opt.net == "ganet":
                output = net(input_var)
                output = output.unsqueeze(1)
            elif opt.net == "dispnetc":
                output = net(input_var)[0]
            else:
                output = net(input_var)[-1]
 
        if i > warmup:
            avg_time.append((time.time() - ss))
            if (i - warmup) % display == 0:
                print('Average inference time: %f' % np.mean(avg_time))
                mbytes = 1024.*1024
                print('GPU memory usage memory_allocated: %d MBytes, max_memory_allocated: %d MBytes, memory_cached: %d MBytes, max_memory_cached: %d MBytes, CPU memory usage: %d MBytes' %  \
                    (ct.memory_allocated()/mbytes, ct.max_memory_allocated()/mbytes, ct.memory_cached()/mbytes, ct.max_memory_cached()/mbytes, process.memory_info().rss/mbytes))
                avg_time = []

        output = scale_disp(output, (output.size()[0], 540, 960))
        disp = output[:, 0, :, :]

        for j in range(num_of_samples):

            name_items = sample_batched['img_names'][0][j].split('/')
            # write disparity to file
	    output_disp = disp[j]
            np_disp = disp[j].data.cpu().numpy()

            print('Batch[{}]: {}, average disp: {}({}-{}).'.format(i, j, np.mean(np_disp), np.min(np_disp), np.max(np_disp)))
            save_name = '_'.join(name_items).replace(".png", "_d.png")# for girl02 dataset
            print('Name: {}'.format(save_name))

            skimage.io.imsave(os.path.join(result_path, save_name),(np_disp*256).astype('uint16'))

            #save_name = '_'.join(name_items).replace("png", "pfm")# for girl02 dataset
            #print('Name: {}'.format(save_name))
            #np_disp = np.flip(np_disp, axis=0)
            #save_pfm('{}/{}'.format(result_path, save_name), np_disp)
            


    print('Evaluation time used: {}'.format(time.time()-s))
        

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--net', type=str, help='indicate the name of net', default='fadnet', choices=SUPPORT_NETS)
    parser.add_argument('--model', type=str, help='model to load', default='best.pth')
    parser.add_argument('--filelist', type=str, help='file list', default='FlyingThings3D_release_TEST.list')
    parser.add_argument('--filepath', type=str, help='file path', default='./data')
    parser.add_argument('--devices', type=str, help='devices', default='0')
    parser.add_argument('--display', type=int, help='Num of samples to print', default=10)
    parser.add_argument('--rp', type=str, help='result path', default='./result')
    parser.add_argument('--flowDiv', type=float, help='flow division', default='1.0')
    parser.add_argument('--batchSize', type=int, help='mini batch size', default=1)

    opt = parser.parse_args()
    detect(opt)
