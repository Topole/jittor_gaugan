"""
Copyright (C) 2019 NVIDIA Corporation.  All rights reserved.
Licensed under the CC BY-NC-SA 4.0 license (https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode).
"""

import jittor as jt
from jittor import init
from jittor import nn
from models.networks.architecture import VGG19
import cv2
import numpy as np
import util.util as util


# Defines the GAN loss which uses either LSGAN or the regular GAN.
# When LSGAN is used, it is basically same as MSELoss,
# but it abstracts away the need to create the target label tensor
# that has the same size as the input
class GANLoss(nn.Module):
    def __init__(self, gan_mode, target_real_label=0.99, target_fake_label=0.01,
                 tensor=jt.float32, opt=None):
        super(GANLoss, self).__init__()
        self.real_label = target_real_label
        self.fake_label = target_fake_label
        self.real_label_tensor = None
        self.fake_label_tensor = None
        self.zero_tensor = None
        self.Tensor = tensor
        self.gan_mode = gan_mode
        self.opt = opt
        if gan_mode == 'ls':
            pass
        elif gan_mode == 'original':
            pass
        elif gan_mode == 'w':
            pass
        elif gan_mode == 'hinge':
            pass
        else:
            raise ValueError('Unexpected gan_mode {}'.format(gan_mode))

    def get_target_tensor(self, input, target_is_real):
        if target_is_real:
            if self.real_label_tensor is None:
                self.real_label_tensor = self.Tensor(1).fill_(self.real_label)
                self.real_label_tensor.requires_grad_(False)
            return self.real_label_tensor.expand_as(input)
        else:
            if self.fake_label_tensor is None:
                self.fake_label_tensor = self.Tensor(1).fill_(self.fake_label)
                self.fake_label_tensor.requires_grad_(False)
            return self.fake_label_tensor.expand_as(input)

    def get_zero_tensor(self, input):
        if self.zero_tensor is None:
            self.zero_tensor = self.Tensor(0.)
            # self.zero_tensor.requires_grad_(False)
        return self.zero_tensor.expand_as(input)

    def loss(self, input, target_is_real, for_discriminator=True):
        if self.gan_mode == 'original':  # cross entropy loss
            target_tensor = self.get_target_tensor(input, target_is_real)
            loss = nn.binary_cross_entropy_with_logits(input, target_tensor)
            return loss
        elif self.gan_mode == 'ls':
            target_tensor = self.get_target_tensor(input, target_is_real)
            return nn.mse_loss(input, target_tensor)
        elif self.gan_mode == 'hinge':
            if for_discriminator:
                if target_is_real:
                    minval = jt.minimum(input - 1, self.get_zero_tensor(input))
                    loss = -jt.mean(minval)
                else:
                    minval = jt.minimum(-input - 1,
                                        self.get_zero_tensor(input))
                    loss = -jt.mean(minval)
            else:
                assert target_is_real, "The generator's hinge loss must be aiming for real"
                loss = -jt.mean(input)
            return loss
        else:
            # wgan
            if target_is_real:
                return -input.mean()
            else:
                return input.mean()

    def __call__(self, input, target_is_real, for_discriminator=True):
        # computing loss is a bit complicated because |input| may not be
        # a tensor, but list of tensors in case of multiscale discriminator
        if isinstance(input, list):
            loss = 0
            for pred_i in input:
                if isinstance(pred_i, list):
                    pred_i = pred_i[-1]
                loss_tensor = self.loss(
                    pred_i, target_is_real, for_discriminator)
                bs = 1 if len(loss_tensor.size()) == 0 else loss_tensor.size(0)
                new_loss = jt.mean(loss_tensor.view(bs, -1), dim=1)
                loss += new_loss
            return loss / len(input)
        else:
            return self.loss(input, target_is_real, for_discriminator)


# Perceptual loss that uses a pretrained VGG network
class VGGLoss(nn.Module):
    def __init__(self, gpu_ids):
        super(VGGLoss, self).__init__()
        self.vgg = VGG19()
        self.criterion = nn.L1Loss()
        self.weights = [1.0 / 32, 1.0 / 16, 1.0 / 8, 1.0 / 4, 1.0]

    def execute(self, x, y):
        x_vgg, y_vgg = self.vgg(x), self.vgg(y)
        loss = 0
        for i in range(len(x_vgg)):
            loss += self.weights[i] * \
                self.criterion(x_vgg[i], y_vgg[i].detach())
        return loss


# KL Divergence loss used in VAE with an image encoder
class KLDLoss(nn.Module):
    def execute(self, mu, logvar):
        return -0.5 * jt.sum(1 + logvar - mu.pow(2) - logvar.exp())


class ColorLoss(nn.Module):
    def __init__(self, opt=None):
        super(ColorLoss, self).__init__()
        self.opt = opt

    def get_color_histogram(self, img):
        #process
        img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        b,g,r = cv2.split(img)
        b_hist = cv2.calcHist([b], [0], None, [256], (0,256))
        g_hist = cv2.calcHist([g], [0], None, [256], (0,256))
        r_hist = cv2.calcHist([r], [0], None, [256], (0,256))
        return b_hist,g_hist,r_hist

    def get_color_correlation_coefficient(self, img1, img2):
        #get color hist
        b_hist1,g_hist1,r_hist1 = self.get_color_histogram(img1)
        b_hist2,g_hist2,r_hist2 = self.get_color_histogram(img2)
        #calculate
        b_correl = cv2.compareHist(b_hist1,b_hist2, cv2.HISTCMP_CORREL)
        g_correl = cv2.compareHist(g_hist1,g_hist2, cv2.HISTCMP_CORREL)
        r_correl = cv2.compareHist(r_hist1,r_hist2, cv2.HISTCMP_CORREL)

    #     b_correl = np.corrcoef(b_hist1.flatten(),b_hist2.flatten())[0][1]
    #     g_correl = np.corrcoef(g_hist1.flatten(),g_hist2.flatten())[0][1]
    #     r_correl = np.corrcoef(r_hist1.flatten(),r_hist2.flatten())[0][1]
        avg_correl = (b_correl+g_correl+r_correl)/3
        return avg_correl, b_correl, g_correl, r_correl
    
    def execute(self, img1, img2):
        ccc = []
        img1 = util.tensor2im(img1, tile=self.opt.batchSize > 8)
        img2 = util.tensor2im(img2, tile=self.opt.batchSize > 8)
        # print('fakeshape: ',img1.shape, 'realshape: ',img2.shape)
        # print('showfake',img1.max(),img2.min())
        # print('showreal',img1.max(),img2.min())
        for i in range(img1.shape[0]):
            ccc.append(self.get_color_correlation_coefficient(img1[i],img2[i])[1:])
        ccc = jt.Var(ccc)
        return (1-ccc.mean())