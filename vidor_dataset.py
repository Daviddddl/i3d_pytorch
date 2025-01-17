import json
import os
import os.path

import cv2
import numpy as np
import torch
import torch.utils.data as data_utl

from tqdm import tqdm
from dataset.vidor import VidOR
from frames import extract_all_frames


def video_to_tensor(pic):
    """Convert a ``numpy.ndarray`` to tensor.
    Converts a numpy.ndarray (T x H x W x C)
    to a torch.FloatTensor of shape (C x T x H x W)

    Args:
         pic (numpy.ndarray): Video to be converted to tensor.
    Returns:
         Tensor: Converted video.
    """
    return torch.from_numpy(pic.transpose([3, 0, 1, 2]))


def load_rgb_frames(video_path, image_dir, begin, end, extract_frames=False):
    """
    :param video_path: if u need 2 extract frames, but b careful, this setting needs a long time!
    :param image_dir: This is image dir, but not same with extract frames func
    :param begin:
    :param end:
    :param extract_frames:
    :return:
    """
    frames = []
    video_path_splits = video_path.split('/')
    image_dir_path = os.path.join(image_dir, video_path_splits[-2], video_path_splits[-1][:-4])

    if extract_frames:
        # Be careful! This step will take a long time!
        extract_all_frames(video_path, image_dir_path)

    for i in range(begin, end):
        img_path = os.path.join(image_dir_path, str(i).zfill(6) + '.jpg')
        if os.path.exists(img_path):
            img = cv2.imread(img_path)[:, :, [2, 1, 0]]
            w, h, c = img.shape
            if w < 226 or h < 226:
                d = 226. - min(w, h)
                sc = 1 + d / min(w, h)
                img = cv2.resize(img, dsize=(0, 0), fx=sc, fy=sc)
            img = (img / 255.) * 2 - 1
            frames.append(img)
        else:
            if len(frames) >= 1:
                frames.append(frames[-1])
    # final relength the frames list
    for miss_frame in range(end - begin - len(frames)):
        frames.insert(0, frames[0])

    return np.asarray(frames, dtype=np.float32)


def load_flow_frames(image_dir, vid, start, num):
    frames = []
    for i in range(start, start + num):
        imgx = cv2.imread(os.path.join(image_dir, vid, vid + '-' + str(i).zfill(6) + 'x.jpg'), cv2.IMREAD_GRAYSCALE)
        imgy = cv2.imread(os.path.join(image_dir, vid, vid + '-' + str(i).zfill(6) + 'y.jpg'), cv2.IMREAD_GRAYSCALE)

        w, h = imgx.shape
        if w < 224 or h < 224:
            d = 224. - min(w, h)
            sc = 1 + d / min(w, h)
            imgx = cv2.resize(imgx, dsize=(0, 0), fx=sc, fy=sc)
            imgy = cv2.resize(imgy, dsize=(0, 0), fx=sc, fy=sc)

        imgx = (imgx / 255.) * 2 - 1
        imgy = (imgy / 255.) * 2 - 1
        img = np.asarray([imgx, imgy]).transpose([1, 2, 0])
        frames.append(img)
    return np.asarray(frames, dtype=np.float32)


def make_vidor_dataset(anno_rpath, splits, video_rpath, task, low_memory=True):
    vidor_dataset = VidOR(anno_rpath, video_rpath, splits, low_memory)
    if task not in ['object', 'action', 'relation']:
        print(task, "is not supported! ")
        exit()

    vidor_dataset_list = []
    if task == 'action':
        with open('actions.json', 'r') as action_f:
            actions = json.load(action_f)['actions']

        for each_split in splits:
            print('Preparing: ', each_split)
            get_index_list = vidor_dataset.get_index(each_split)
            pbar = tqdm(total=len(get_index_list))
            for ind in get_index_list:
                for each_ins in vidor_dataset.get_action_insts(ind):
                    video_path = vidor_dataset.get_video_path(ind)
                    start_f, end_f = each_ins['duration']
                    label = np.full((1, end_f - start_f), actions.index(each_ins['category']))
                    vidor_dataset_list.append((video_path, label, start_f, end_f))
                pbar.update(1)

            pbar.close()
    return vidor_dataset_list


class VidorPytorchTrain(data_utl.Dataset):

    def __init__(self, anno_rpath, splits, video_rpath,
                 frames_rpath, mode, save_dir, task='action',
                 transforms=None, low_memory=True):
        self.data = make_vidor_dataset(
            anno_rpath=anno_rpath,
            splits=splits,
            video_rpath=video_rpath,
            task=task,
            low_memory=low_memory)
        self.frames_rpath = frames_rpath
        self.transforms = transforms
        self.mode = mode
        self.task = task
        self.save_dir = save_dir

    def __getitem__(self, index):
        """
        Args:
            index (int): Index

        Returns:
            tuple: (image, target) where target is class_index of the target class.
        """

        video_path, label, start_f, end_f = self.data[index]

        vid_paths = video_path.split('/')
        img_dir_path = os.path.join(self.frames_rpath, vid_paths[-2], vid_paths[-1][:-4])
        if os.path.exists(img_dir_path):
            if self.mode == 'rgb':
                imgs = load_rgb_frames(video_path=video_path,
                                       image_dir=self.frames_rpath,
                                       begin=start_f,
                                       end=end_f)
            else:
                # imgs = load_flow_frames(self.root, vid, start_f, 64)
                print('not supported')
            # label = label[:, start_f: end_f]

            imgs = self.transforms(imgs)

            # return video_to_tensor(imgs), 0     # correct
            # return 0, torch.from_numpy(label)     # runtimeError sizes must be non-negative
            return video_to_tensor(imgs), torch.from_numpy(label)
        return 0, 0

    def __len__(self):
        return len(self.data)


class VidorPytorchExtract(data_utl.Dataset):
    def __init__(self, anno_rpath, save_dir, splits,
                 video_rpath, frames_rpath, mode, task='action',
                 transforms=None, low_memory=True):
        self.data = make_vidor_dataset(
            anno_rpath=anno_rpath,
            splits=splits,
            video_rpath=video_rpath,
            task=task,
            low_memory=low_memory)
        self.frames_rpath = frames_rpath
        self.splits = splits
        self.transforms = transforms
        self.mode = mode
        self.save_dir = save_dir

    def __getitem__(self, index):
        """
        Args:
            index (int): Index

        Returns:
            tuple: (image, target) where target is class_index of the target class.
        """

        video_path, label, start_f, end_f = self.data[index]
        vid_paths = video_path.split('/')
        img_dir_path = os.path.join(self.frames_rpath, vid_paths[-2], vid_paths[-1][:-4])

        if os.path.exists(img_dir_path + '.npy'):
            return 0, 0, vid_paths[-2], vid_paths[-1][:-4]

        if os.path.exists(img_dir_path):
            if self.mode == 'rgb':
                imgs = load_rgb_frames(video_path=video_path,
                                       image_dir=self.frames_rpath,
                                       begin=start_f,
                                       end=end_f)
            else:
                # imgs = load_flow_frames(self.root, vid, start_f, 64)
                print('not supported')

            imgs = self.transforms(imgs)
            return video_to_tensor(imgs), torch.from_numpy(label), vid_paths[-2], vid_paths[-1][:-4]
        return -1, -1, vid_paths[-2], vid_paths[-1][:-4]

    def __len__(self):
        return len(self.data)


if __name__ == '__main__':
    import videotransforms
    from torchvision import transforms
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-where', type=str, default="local")
    parser.add_argument('-split', type=str, default="test")
    parser.add_argument('-dataset', type=str, default='ext')
    args = parser.parse_args()

    local_anno_rpath = '/home/daivd/PycharmProjects/vidor/annotation'
    local_video_rpath = '/home/daivd/PycharmProjects/vidor/test_vids'
    gpu_anno_rpath = '/storage/dldi/PyProjects/vidor/annotation'
    gpu_video_rpath = '/storage/dldi/PyProjects/vidor/train_vids'
    mode = 'rgb'
    save_dir = 'output/features/'
    low_memory = True
    batch_size = 1

    train_transforms = transforms.Compose([videotransforms.RandomCrop(224),
                                           videotransforms.RandomHorizontalFlip()])

    test_transforms = transforms.Compose([videotransforms.CenterCrop(224)])

    task = 'action'

    if args.dataset == 'train':
        Dataset = VidorPytorchTrain
    else:
        Dataset = VidorPytorchExtract

    if args.where == 'gpu':
        anno_rpath = gpu_anno_rpath
        video_rpath = gpu_video_rpath
        frames_rpath = 'data/Vidor_rgb/JPEGImages/'

    else:
        anno_rpath = local_anno_rpath
        video_rpath = local_video_rpath
        frames_rpath = '/home/daivd/PycharmProjects/vidor/Vidor_rgb/JPEGImages/'

    if args.split == 'train':

        dataset = Dataset(anno_rpath=anno_rpath,
                          splits=['training'],
                          video_rpath=video_rpath,
                          mode=mode,
                          task=task,
                          save_dir=save_dir,
                          frames_rpath=frames_rpath,
                          transforms=train_transforms,
                          low_memory=low_memory)

        dataloader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=36,
                                                 pin_memory=True)
    else:
        val_dataset = Dataset(anno_rpath=anno_rpath,
                              splits=['validation'],
                              video_rpath=video_rpath,
                              mode=mode,
                              save_dir=save_dir,
                              frames_rpath=frames_rpath,
                              task=task,
                              transforms=test_transforms,
                              low_memory=low_memory)
        dataloader = torch.utils.data.DataLoader(val_dataset, batch_size=batch_size, shuffle=True, num_workers=36,
                                                 pin_memory=True)

    for data in dataloader:
        # get the inputs
        inputs, labels, a, b = data
        if inputs.tolist()[0] != -1:
            print(inputs.size())        # torch.Size([1, 3, 4, 224, 224])
            print(labels.size())        # torch.Size([1, 1, 4])
